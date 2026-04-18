from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.v1.schemas.infrastructure_component import InfrastructureComponentSummary


VALID_CHANGE_TYPES = {"configuration", "infrastructure", "code_deployment"}


def _require_chronological(start: datetime, end: datetime, label: str) -> None:
    if end <= start:
        raise ValueError(f"{label}: end must be after start")


def _validate_outage(
    has_outage: bool, outage_start: Optional[datetime], outage_end: Optional[datetime]
) -> None:
    if has_outage:
        if outage_start is None or outage_end is None:
            raise ValueError(
                "outage_start and outage_end are required when has_outage is true"
            )
        _require_chronological(outage_start, outage_end, "outage")


class ChangeRequestCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=250)
    description: Optional[str] = None
    change_type: str
    lifecycle_id: int
    subsystem_id: Optional[int] = None
    environment_ids: list[int] = Field(default_factory=list)
    host_ids: list[int] = Field(default_factory=list)
    release_id: Optional[int] = None
    has_outage: bool = False
    outage_start: Optional[datetime] = None
    outage_end: Optional[datetime] = None
    scheduled_start: datetime
    scheduled_end: datetime
    custom_fields: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _check(self) -> "ChangeRequestCreate":
        if self.change_type not in VALID_CHANGE_TYPES:
            raise ValueError(
                f"change_type must be one of {sorted(VALID_CHANGE_TYPES)}"
            )
        if not self.environment_ids and not self.host_ids:
            raise ValueError(
                "At least one of environment_ids or host_ids is required"
            )
        _require_chronological(self.scheduled_start, self.scheduled_end, "scheduled")
        _validate_outage(self.has_outage, self.outage_start, self.outage_end)
        return self


class ChangeRequestUpdate(BaseModel):
    """All fields optional; validators run only on fields that were supplied."""

    title: Optional[str] = Field(None, min_length=1, max_length=250)
    description: Optional[str] = None
    change_type: Optional[str] = None
    subsystem_id: Optional[int] = None
    environment_ids: Optional[list[int]] = None
    host_ids: Optional[list[int]] = None
    release_id: Optional[int] = None
    has_outage: Optional[bool] = None
    outage_start: Optional[datetime] = None
    outage_end: Optional[datetime] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    custom_fields: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def _check(self) -> "ChangeRequestUpdate":
        if self.change_type is not None and self.change_type not in VALID_CHANGE_TYPES:
            raise ValueError(
                f"change_type must be one of {sorted(VALID_CHANGE_TYPES)}"
            )
        if self.scheduled_start is not None and self.scheduled_end is not None:
            _require_chronological(self.scheduled_start, self.scheduled_end, "scheduled")
        return self


class ChangeRequestTransition(BaseModel):
    to_state: str = Field(..., min_length=1)
    notes: Optional[str] = None


class ChangeHistoryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_state: Optional[str]
    to_state: Optional[str]
    field_name: Optional[str]
    old_value: Optional[Any]
    new_value: Optional[Any]
    changed_by: int
    changed_at: datetime
    notes: Optional[str]


class EnvironmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ChangeRequestResponse(BaseModel):
    """Response shape — resolved lists replace the legacy single environment_id FK."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    title: str
    description: Optional[str]
    change_type: str
    status: str
    lifecycle_id: int
    subsystem_id: Optional[int]
    environment_ids: list[int] = []
    host_ids: list[int] = []
    environments: list[EnvironmentSummary] = []
    hosts: list[InfrastructureComponentSummary] = []
    derived_environment_ids: list[int] = []
    derived_environments: list[EnvironmentSummary] = []
    release_id: Optional[int]
    has_outage: bool
    outage_start: Optional[datetime]
    outage_end: Optional[datetime]
    scheduled_start: datetime
    scheduled_end: datetime
    custom_fields: Optional[dict[str, Any]]
    raised_by: int
    created_at: datetime
    updated_at: datetime


class ChangeRequestDetailResponse(ChangeRequestResponse):
    history: list[ChangeHistoryEntry] = []


# ── Outage × booking conflict preview ───────────────────────────────────────

class PreviewOutageConflictsRequest(BaseModel):
    environment_ids: list[int] = Field(default_factory=list)
    host_ids: list[int] = Field(default_factory=list)
    outage_start: datetime
    outage_end: datetime
    exclude_change_request_id: Optional[int] = None

    @model_validator(mode="after")
    def _check(self) -> "PreviewOutageConflictsRequest":
        _require_chronological(self.outage_start, self.outage_end, "outage")
        if not self.environment_ids and not self.host_ids:
            raise ValueError(
                "At least one of environment_ids or host_ids is required"
            )
        return self


class OutageConflictBooking(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    environment_name: str
    project_name: str
    start_date: datetime
    end_date: datetime
    status: str


class OutageConflictEnvironment(BaseModel):
    environment_id: int
    environment_name: str
    conflicts: list[OutageConflictBooking] = []


class PreviewOutageConflictsResponse(BaseModel):
    environments: list[OutageConflictEnvironment] = []
    derived_environment_ids: list[int] = []
    derived_environments: list[EnvironmentSummary] = []
