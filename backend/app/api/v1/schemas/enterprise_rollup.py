from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SystemRollupRow(BaseModel):
    system_id: int
    system_name: str
    # project_name → list of roles that project contributes for this system
    roles_by_project: dict[str, list[str]]


class ScopeRollupFilters(BaseModel):
    change_kind: Optional[str] = None
    status: Optional[str] = None
    project_release_id: Optional[int] = None
    system_id: Optional[int] = None
    search: Optional[str] = None


class TimelinePhaseRead(BaseModel):
    release_id: int
    release_name: str
    release_kind: str
    phase_id: Optional[int] = None
    phase_name: str
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    status: Optional[str] = None


class TimelineDependencyEdge(BaseModel):
    from_release_id: int
    to_release_id: int
    alert: Optional[str] = None


class TimelineRollupRead(BaseModel):
    enterprise_phases: list[TimelinePhaseRead]
    child_phases_by_release: dict[int, list[TimelinePhaseRead]]
    dependencies: list[TimelineDependencyEdge]


class MemberStateCount(BaseModel):
    state: str
    count: int
    projects: list[str]


class MemberRollupRow(BaseModel):
    project_release_id: int
    project_release_name: str
    status: str
    admitted_at: Optional[datetime] = None
    late_scope: bool


class ScopeRollupItem(BaseModel):
    release_change_id: int
    project_release_id: int
    project_release_name: str
    external_key: Optional[str] = None
    title: str
    change_kind: str
    external_status: Optional[str] = None
    system_id: Optional[int] = None
    system_name: Optional[str] = None


class EnterpriseReportEvent(BaseModel):
    release_id: int
    release_name: str
    occurred_at: datetime
    event_type: str
    description: Optional[str] = None


class EnterpriseReportRead(BaseModel):
    enterprise_id: int
    name: str
    status: str
    target_date: Optional[datetime] = None
    actual_date: Optional[datetime] = None
    description: Optional[str] = None
    members: list[MemberRollupRow]
    systems: list[SystemRollupRow]
    scope_by_project: dict[str, list[ScopeRollupItem]]
    events: list[EnterpriseReportEvent]
    dependencies: list[TimelineDependencyEdge]
    generated_at: str  # ISO-8601
    generated_by: str  # username
