import uuid
from typing import Sequence

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.db.database import get_db
from app.models.booking import Booking, BookingStatus
from app.models.event import Event
from app.models.user import User, UserRole
from app.schemas.event import EventCreate, EventResponse, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    event_in: EventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    if current_user.role != UserRole.ORGANIZER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organizers can create events",
        )

    db_event = Event(
        title=event_in.title,
        description=event_in.description,
        location=event_in.location,
        event_date=event_in.event_date,
        total_tickets=event_in.total_tickets,
        available_tickets=event_in.total_tickets,
        organizer_id=current_user.id,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


@router.get("", response_model=list[EventResponse])
def list_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Sequence[Event]:
    # Both customers and organizers can list events
    return db.query(Event).all()


@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    # Both customers and organizers can view events
    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@router.patch("/{event_id}", response_model=EventResponse)
def update_event(
    event_id: uuid.UUID,
    event_update: EventUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    if current_user.role != UserRole.ORGANIZER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organizers can update events",
        )

    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if event.organizer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update an event you do not own",
        )

    update_data = event_update.model_dump(exclude_unset=True)
    if not update_data:
        return event

    if "total_tickets" in update_data:
        new_total = update_data["total_tickets"]
        
        # Calculate currently booked tickets
        booked_tickets = db.query(func.sum(Booking.quantity)).filter(
            Booking.event_id == event.id,
            Booking.status == BookingStatus.CONFIRMED,
        ).scalar() or 0

        if new_total < booked_tickets:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reduce total tickets below already booked tickets ({booked_tickets})",
            )
            
        # Update available tickets safely
        event.available_tickets = new_total - booked_tickets

    # Apply other updates
    for field, value in update_data.items():
        if hasattr(event, field) and field != "total_tickets":
            setattr(event, field, value)
            
    if "total_tickets" in update_data:
        event.total_tickets = update_data["total_tickets"]

    # Increment version
    event.version += 1
    
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.role != UserRole.ORGANIZER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only organizers can delete events",
        )

    event = db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    if event.organizer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete an event you do not own",
        )

    try:
        db.delete(event)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete event with existing bookings",
        ) from None
