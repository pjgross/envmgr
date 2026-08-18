"""B5 Task 5 — initiating a decommission.

`DecommissionRead.state` is REQUIRED and has no default, the same reason A4's
`EscalationRead.state` is required: `EnvironmentDecommission` has no `state`
column (it stores facts only — see the service module docstring), so the
value can never come from `model_validate(row)`. It is set explicitly in the
response builder, computed by `environment_decommission_service.
decommission_state` from one clock taken once per request — the same call B4
made for `BookingResponse.protection_level`.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DecommissionCreate(BaseModel):
    """The WRITE model. `extra='forbid'` so a misspelled key is a 422, not a
    silently dropped field."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    # Optional: the initiator may push the teardown date LATER than the
    # tenant's notice period, never earlier. Omitted, it defaults to
    # warned_at + policy.decommission_notice_days.
    scheduled_teardown_at: Optional[datetime] = None


class DecommissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    reason: str
    warned_at: datetime
    scheduled_teardown_at: datetime
    initiated_by: int

    extension_requested_at: Optional[datetime]
    extension_reason: Optional[str]
    extension_until: Optional[datetime]
    extension_decided_at: Optional[datetime]
    extension_granted: Optional[bool]

    torn_down_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancel_reason: Optional[str]

    # REQUIRED, computed — never model_validate'd. See the module docstring.
    state: str
