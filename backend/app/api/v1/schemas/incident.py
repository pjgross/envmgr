from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

SEVERITIES = {"P1", "P2", "P3", "P4"}


class IncidentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    severity: str
    detected_at: Optional[datetime] = None          # defaults to now in the service
    environment_id: Optional[int] = None
    deployment_id: Optional[int] = None
    release_id: Optional[int] = None
    fix_release_id: Optional[int] = None
    system_id: Optional[int] = None
    subsystem_id: Optional[int] = None
    source: str = "manual"
    external_ref: Optional[str] = None
    lifecycle_template_id: Optional[int] = None
    custom_fields: Optional[dict] = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        if v not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
        return v


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    detected_at: Optional[datetime] = None
    environment_id: Optional[int] = None
    deployment_id: Optional[int] = None
    release_id: Optional[int] = None
    fix_release_id: Optional[int] = None
    system_id: Optional[int] = None
    subsystem_id: Optional[int] = None
    external_ref: Optional[str] = None
    custom_fields: Optional[dict] = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v):
        if v is not None and v not in SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(SEVERITIES)}")
        return v


class IncidentTransition(BaseModel):
    to_state: str


class ReleaseSummary(BaseModel):
    id: int
    name: str
    target_date: Optional[datetime] = None
    status: str
    model_config = ConfigDict(from_attributes=True)


class ReleaseChangeRow(BaseModel):
    id: int
    title: str
    epic_id: Optional[int] = None
    model_config = ConfigDict(from_attributes=True)


class TransitionOption(BaseModel):
    to_state: str
    label: str


class StatusHistoryRow(BaseModel):
    from_state: Optional[str]
    to_state: str
    changed_by: Optional[int]
    changed_at: datetime
    model_config = ConfigDict(from_attributes=True)


class IncidentPirCitation(BaseModel):
    """One review that cites this incident as evidence.

    The PIR fixes the process that let the incident reach production; it does
    not fix the incident. `open_action_count` is here so the reader can see
    whether the process fix is still outstanding without opening the release.
    """

    pir_id: int
    release_id: int
    release_name: str
    pir_status: str
    finding_id: int
    finding_title: str
    root_cause: Optional[str] = None
    note: Optional[str] = None
    action_count: int
    open_action_count: int


class IncidentListRow(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]
    system_id: Optional[int]
    system_name: Optional[str] = None
    environment_id: Optional[int]
    environment_name: Optional[str] = None
    release_id: Optional[int]
    release_name: Optional[str] = None
    fix_release: Optional[ReleaseSummary] = None
    pir_status: str = "none"
    model_config = ConfigDict(from_attributes=True)


class IncidentDetail(BaseModel):
    id: int
    title: str
    description: Optional[str]
    severity: str
    status: str
    detected_at: datetime
    resolved_at: Optional[datetime]
    source: str
    external_ref: Optional[str]
    environment_id: Optional[int]
    environment_name: Optional[str] = None
    deployment_id: Optional[int]
    release_id: Optional[int]
    release: Optional[ReleaseSummary] = None
    fix_release_id: Optional[int]
    fix_release: Optional[ReleaseSummary] = None
    fix_release_changes_by_epic: dict[str, list[ReleaseChangeRow]] = {}
    system_id: Optional[int]
    system_name: Optional[str] = None
    subsystem_id: Optional[int]
    subsystem_name: Optional[str] = None
    custom_fields: Optional[dict]
    allowed_transitions: list[TransitionOption] = []
    status_history: list[StatusHistoryRow] = []
    # A list, not a single ref: one incident can be cited by the reviews of
    # several releases, and by more than one finding within one review.
    pir_citations: list[IncidentPirCitation] = []
    model_config = ConfigDict(from_attributes=True)
