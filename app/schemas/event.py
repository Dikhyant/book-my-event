from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID


class EventBase(BaseModel):
    title: str = Field(..., description="The title of the event")
    description: str | None = Field(None, description="Detailed description of the event")
    location: str | None = Field(None, description="Location of the event")
    event_date: datetime = Field(..., description="Date and time of the event")
    total_tickets: int = Field(..., gt=0, description="Total number of tickets available")


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    location: str | None = None
    event_date: datetime | None = None
    total_tickets: int | None = Field(None, gt=0)


class EventResponse(EventBase):
    id: UUID
    available_tickets: int
    organizer_id: UUID
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
