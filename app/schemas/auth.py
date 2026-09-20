from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole


class UserResponse(BaseModel):
    id: UUID
    name: str
    role: UserRole

    model_config = ConfigDict(from_attributes=True)