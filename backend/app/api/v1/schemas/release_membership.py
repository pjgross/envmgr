from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ReleaseMembershipCreate(BaseModel):
    project_release_id: int
    notes: Optional[str] = None


class MembershipRejectRequest(BaseModel):
    notes: str = Field(..., min_length=1)


class MembershipRemoveRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class ReleaseMembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    enterprise_release_id: int
    project_release_id: int
    project_release_name: Optional[str] = None
    project_release_status: Optional[str] = None
    enterprise_release_name: Optional[str] = None
    state: str
    requested_by: int
    requested_by_username: Optional[str] = None
    requested_at: datetime
    decided_by: Optional[int] = None
    decided_by_username: Optional[str] = None
    decided_at: Optional[datetime] = None
    removed_by: Optional[int] = None
    removed_by_username: Optional[str] = None
    removed_at: Optional[datetime] = None
    removal_reason: Optional[str] = None
    late_scope: bool
    notes: Optional[str] = None


class MembershipSummary(BaseModel):
    pending: int
    accepted: int
    rejected: int
    withdrawn: int
    removed: int
