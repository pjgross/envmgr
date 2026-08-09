from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from app.api.v1.schemas.booking_request import EnvBookingSummary
from app.api.v1.schemas.contention import ContentionRead


class ConflictAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_by: Optional[int]
    acknowledged_at: Optional[datetime]


class ConflictItem(BaseModel):
    """One conflicting booking, what we have said about it, and what A4 says.

    `contention` is REQUIRED and has no default, deliberately. A defaulted field
    is what left `has_unacknowledged_conflicts` dead at every construction site
    since it shipped: the site compiles, the suite stays green, and every reader
    is told the wrong thing. A required field guards only OMISSION — a site can
    still satisfy it with a constant — so
    `test_the_four_outcomes_read_through_the_endpoint_over_one_mixed_population`
    asserts the value against `verdict_for_pair` for the same pair, over a page
    holding all four outcomes at once.
    """

    other_booking: EnvBookingSummary
    contention: ContentionRead
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
    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_at: datetime
    acknowledged_by: UserRef

    source_booking: EnvBookingSummary
    source_request: RequestContextRef
