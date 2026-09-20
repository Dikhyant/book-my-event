import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.booking import BookingStatus


class BookingCreate(BaseModel):
    event_id: uuid.UUID
    quantity: int = Field(gt=0, description="Quantity must be a positive integer")


class BookingResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    event_id: uuid.UUID
    quantity: int
    status: BookingStatus
    created_at: datetime

    class Config:
        from_attributes = True
