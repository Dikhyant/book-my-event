import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models.booking import Booking
from app.models.user import User, UserRole
from app.schemas.booking import BookingCreate, BookingResponse
from app.services.booking_service import create_booking

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def route_create_booking(
    booking_in: BookingCreate,
    idempotency_key: Optional[uuid.UUID] = Header(None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can create bookings",
        )

    return create_booking(db, current_user.id, booking_in, idempotency_key)


@router.get("", response_model=list[BookingResponse])
def list_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Booking]:
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can view their bookings",
        )

    bookings = db.query(Booking).filter(Booking.customer_id == current_user.id).all()
    return bookings


@router.get("/{booking_id}", response_model=BookingResponse)
def get_booking(
    booking_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Booking:
    if current_user.role != UserRole.CUSTOMER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only customers can view their bookings",
        )

    booking = db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.customer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot view another customer's booking",
        )

    return booking
