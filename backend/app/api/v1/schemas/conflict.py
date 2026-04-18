from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.booking_request import EnvBookingSummary


class ConflictAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_by: Optional[int]
    acknowledged_at: Optional[datetime]


class ConflictItem(BaseModel):
    other_booking: EnvBookingSummary
    ack: Optional[ConflictAckRead] = None


class ConflictAckUpsert(BaseModel):
    willing_to_share: bool
    notes: Optional[str] = None


class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str


class RequestContextRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_name: str
    notes: Optional[str] = None
    context_tag: str
    exclusive_use_requested: bool
    booked_by: UserRef


class ReceivedFeedbackItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_at: datetime
    acknowledged_by: UserRef

    source_booking: EnvBookingSummary
    source_request: RequestContextRef
