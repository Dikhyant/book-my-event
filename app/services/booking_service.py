import uuid

from fastapi import HTTPException, status
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.schemas.booking import BookingCreate


def create_booking(
    db: Session,
    customer_id: uuid.UUID,
    booking_in: BookingCreate,
    idempotency_key: uuid.UUID | None = None,
) -> Booking:
    # Handle idempotency
    if idempotency_key is not None:
        existing_booking = (
            db.query(Booking)
            .filter(
                Booking.customer_id == customer_id,
                Booking.idempotency_key == idempotency_key,
            )
            .first()
        )
        if existing_booking:
            return existing_booking

    # Atomic ticket decrement
    stmt = (
        update(Event)
        .where(
            Event.id == booking_in.event_id,
            Event.available_tickets >= booking_in.quantity,
        )
        .values(available_tickets=Event.available_tickets - booking_in.quantity)
    )
    result = db.execute(stmt)

    if result.rowcount == 0:
        # Check if event exists to differentiate between 404 and 409
        event = db.get(Event, booking_in.event_id)
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Event not found",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Insufficient available tickets",
            )

    # Insert the booking
    new_booking = Booking(
        customer_id=customer_id,
        event_id=booking_in.event_id,
        quantity=booking_in.quantity,
        idempotency_key=idempotency_key,
        status=BookingStatus.CONFIRMED,
    )
    db.add(new_booking)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(new_booking)

    from app.workers.tasks.booking_email import send_booking_confirmation
    send_booking_confirmation.delay(str(new_booking.id))

    return new_booking
