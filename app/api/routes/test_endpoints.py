import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import SessionLocal, get_db
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.booking import BookingCreate
from app.services.booking_service import create_booking

# Note: This endpoint is for development/load testing only and should be disabled or removed before production deployment.
router = APIRouter(prefix="/test", tags=["test"])


class ConcurrentBookingRequest(BaseModel):
    event_id: uuid.UUID
    customer_ids: list[uuid.UUID] = Field(..., min_length=2, max_length=20)
    quantity: int = Field(..., gt=0)


class CustomerResult(BaseModel):
    customer_id: uuid.UUID
    status_code: int
    booking_id: uuid.UUID | None = None
    error: str | None = None


class ConcurrentBookingResponse(BaseModel):
    event_id: uuid.UUID
    total_requests: int
    successful_bookings: int
    insufficient_tickets: int
    other_errors: int
    final_available_tickets: int
    results: list[CustomerResult]


def _run_single_booking(
    customer_id: uuid.UUID,
    event_id: uuid.UUID,
    quantity: int,
    idempotency_key: uuid.UUID,
) -> dict[str, Any]:
    # We must use a separate database session for each concurrent thread
    # otherwise SQLAlchemy will raise errors about concurrent usage of a single session
    db = SessionLocal()
    try:
        booking_in = BookingCreate(event_id=event_id, quantity=quantity)
        booking = create_booking(db, customer_id, booking_in, idempotency_key)
        return {
            "customer_id": customer_id,
            "status_code": 201,
            "booking_id": booking.id,
        }
    except HTTPException as e:
        return {
            "customer_id": customer_id,
            "status_code": e.status_code,
            "error": e.detail,
        }
    except Exception as e:
        return {
            "customer_id": customer_id,
            "status_code": 500,
            "error": str(e),
        }
    finally:
        db.close()


@router.post(
    "/concurrent-bookings",
    response_model=ConcurrentBookingResponse,
    description="Development-only endpoint that concurrently attempts bookings for multiple customers to test race-condition protection.",
)
async def create_concurrent_bookings(
    request: ConcurrentBookingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != UserRole.ORGANIZER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organizers can run this test endpoint",
        )

    # Use asyncio.gather and asyncio.to_thread to run synchronous database functions concurrently
    tasks = []
    for customer_id in request.customer_ids:
        idempotency_key = uuid.uuid4()
        tasks.append(
            asyncio.to_thread(
                _run_single_booking,
                customer_id,
                request.event_id,
                request.quantity,
                idempotency_key,
            )
        )

    results = await asyncio.gather(*tasks)

    successful_bookings = 0
    insufficient_tickets = 0
    other_errors = 0

    parsed_results = []
    for r in results:
        parsed_results.append(CustomerResult(**r))
        if r["status_code"] == 201:
            successful_bookings += 1
        elif r["status_code"] == 409:
            insufficient_tickets += 1
        else:
            other_errors += 1

    # Verify final tickets by getting event again
    db.expire_all()  # ensure we fetch fresh data
    event = db.get(Event, request.event_id)
    final_tickets = event.available_tickets if event else 0

    return ConcurrentBookingResponse(
        event_id=request.event_id,
        total_requests=len(request.customer_ids),
        successful_bookings=successful_bookings,
        insufficient_tickets=insufficient_tickets,
        other_errors=other_errors,
        final_available_tickets=final_tickets,
        results=parsed_results,
    )
