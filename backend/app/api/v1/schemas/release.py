# backend/app/api/v1/schemas/release.py
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.release_membership import MembershipSummary


class ReleaseCreate(BaseModel):
    name: str = Field(..., max_length=250)
    description: Optional[str] = None
    release_type: str = Field(..., max_length=50)
    release_kind: str = Field(default="project", max_length=20)
    # Named owning_project_id, not project_id: release_kind='project' above
    # already means "not an enterprise release", and two things called
    # project on one row is how a future reader gets it wrong.
    owning_project_id: Optional[int] = None
    template_id: Optional[int] = None
    lifecycle_template_id: Optional[int] = None  # service falls back to tenant default
    target_date: Optional[datetime] = None
    scope_deadline: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=250)
    description: Optional[str] = None
    release_type: Optional[str] = Field(None, max_length=50)
    owning_project_id: Optional[int] = None
    target_date: Optional[datetime] = None
    scope_deadline: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    release_type: str
    release_kind: str
    owning_project_id: Optional[int] = None
    owning_project_name: Optional[str] = None
    parent_release_id: Optional[int]
    template_id: Optional[int]
    lifecycle_template_id: int
    status: str
    target_date: Optional[datetime]
    actual_date: Optional[datetime]
    scope_deadline: Optional[datetime] = None
    scope_creep_count: int = 0
    custom_fields: Optional[dict[str, Any]] = None
    raised_by: int
    created_at: datetime
    updated_at: datetime
    custom_field_permissions: Optional[dict[str, dict]] = None
    standard_field_permissions: Optional[dict[str, dict]] = None
    membership_summary: Optional[MembershipSummary] = None


class ReleaseTransition(BaseModel):
    to_state: str
    notes: Optional[str] = None


class ReleaseStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    release_id: int
    from_state: Optional[str]
    to_state: str
    changed_by: int
    changed_at: datetime
    notes: Optional[str]


class ReleaseSystemBrief(BaseModel):
    id: int
    name: str
    role: str


class ReleaseListItemRead(ReleaseRead):
    """Extended read schema for list endpoints — includes summary counts."""
    phase_count: int = 0
    scope_count: int = 0
    blocker_count: int = 0
    overdue_criterion_count: int = 0
    # Scope-change KPIs: counts only items whose change_kind has a
    # scope_change_kind_rule with counts_as_scope_change=True for this tenant.
    scope_additions_count: int = 0
    scope_removals_count: int = 0
    scope_change_count: int = 0
    window_status: str = "no_cutoff"
    days_to_cutoff: Optional[int] = None
    systems: list[ReleaseSystemBrief] = []
