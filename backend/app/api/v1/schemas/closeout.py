from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditNote(BaseModel):
    """Body of the four audit routes. `extra="forbid"`: the lifecycle-template
    endpoint's silent-drop history is why every new request schema forbids."""
    model_config = ConfigDict(extra="forbid")
    note: Optional[str] = Field(None, max_length=2000)


class HypercarePhaseRead(BaseModel):
    id: int
    name: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]


class HypercareRead(BaseModel):
    state: str  # none | planned | active | overdue | stable
    phase: Optional[HypercarePhaseRead]
    declared_stable_at: Optional[datetime]
    declared_stable_by_username: Optional[str]


class HandoverRead(BaseModel):
    operations_group_id: Optional[int]
    operations_group_name: Optional[str]
    confirmed_at: Optional[datetime]
    confirmed_by_username: Optional[str]


class PirStateRead(BaseModel):
    exists: bool
    status: Optional[str]
    completed_at: Optional[datetime]


class IncidentWindowItem(BaseModel):
    id: int
    title: str
    severity: str
    status: str
    detected_at: datetime


class IncidentsWindowRead(BaseModel):
    window_start: Optional[datetime]
    window_end: Optional[datetime]
    by_severity: dict[str, int]
    total: int
    items: list[IncidentWindowItem]


class CloseTargetRead(BaseModel):
    state_key: str
    label: str
    requires_pir_complete: bool
    requires_handover_confirmed: bool
    unmet: list[str]
    can_close: bool


class CloseoutRead(BaseModel):
    hypercare: HypercareRead
    handover: HandoverRead
    pir: PirStateRead
    incidents: IncidentsWindowRead
    close_targets: list[CloseTargetRead]
