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
    ack: Optional[ConflictAckRead]


class ConflictAckUpsert(BaseModel):
    willing_to_share: bool
    notes: Optional[str] = None
