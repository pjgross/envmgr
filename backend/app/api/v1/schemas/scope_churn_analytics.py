from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ChurnCohort(BaseModel):
    count: int
    delayed_count: int
    delayed_pct: float
    issue_count: int
    issue_pct: float


class ChurnReleaseRow(BaseModel):
    release_id: int
    name: str
    shipped_at: datetime
    scope_changed: bool
    delayed: bool
    had_issue: bool


class ScopeChurnAnalyticsRead(BaseModel):
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    scope_changed: ChurnCohort
    stable: ChurnCohort
    releases: list[ChurnReleaseRow]
