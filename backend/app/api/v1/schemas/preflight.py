"""Pydantic schemas for the deployment preflight (`can-deploy`) endpoint."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class CanDeployBlocker(BaseModel):
    """A condition that prevents deployment."""

    type: Literal[
        "environment_inactive",
        "exclusive_booking",
        "change_request_outage",
    ]
    ref_kind: Literal["environment", "booking", "change_request"]
    ref_id: int
    title: Optional[str] = None
    until: Optional[datetime] = None
    current_status: Optional[str] = None  # populated for environment_inactive


class CanDeployWarning(BaseModel):
    """An advisory condition that does not block deployment."""

    type: Literal["non_exclusive_booking", "deployment_in_progress"]
    ref_kind: Literal["booking", "deployment"]
    ref_id: int
    title: Optional[str] = None
    until: Optional[datetime] = None
    since: Optional[datetime] = None


class ClaimMatched(BaseModel):
    """Set when a query claim token unlocks an otherwise-blocking exclusive booking."""

    booking_id: int
    matched_via: Literal["booking_id", "release_id"]
    claim_value: int


class CanDeployResponse(BaseModel):
    """Response body for GET /api/v1/webhooks/can-deploy."""

    model_config = ConfigDict(from_attributes=True)

    ok: bool
    environment_slug: str
    subsystem_slug: str
    checked_at: datetime
    blockers: list[CanDeployBlocker]
    warnings: list[CanDeployWarning]
    claim_matched: Optional[ClaimMatched] = None
