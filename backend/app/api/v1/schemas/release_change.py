# backend/app/api/v1/schemas/release_change.py
from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ReleaseChangeCreate(BaseModel):
    external_key: Optional[str] = Field(None, max_length=50)
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    change_kind: str  # story | defect | task | spike
    external_status: Optional[str] = Field(None, max_length=100)
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None
    project_code: Optional[str] = Field(None, max_length=50)
    project_name: Optional[str] = Field(None, max_length=200)


class ReleaseChangeUpdate(BaseModel):
    # NOTE: release_id is intentionally NOT here — use POST /release-changes/{id}/move.
    external_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    external_status: Optional[str] = None
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None
    project_code: Optional[str] = Field(None, max_length=50)
    project_name: Optional[str] = Field(None, max_length=200)


class ReleaseChangeMovePayload(BaseModel):
    """POST /release-changes/{id}/move body. release_id=None unlinks to backlog."""
    release_id: Optional[int] = None
    notes: Optional[str] = None


class ReleaseChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: Optional[int]
    external_key: Optional[str]
    title: str
    description: Optional[str]
    change_kind: str
    external_status: Optional[str]
    system_id: Optional[int]
    custom_fields: Optional[dict[str, Any]]
    jira_project_config_id: Optional[int]
    epic_id: Optional[int]
    source: str
    project_code: Optional[str] = None
    project_name: Optional[str] = None
    # Computed KPIs — populated by service; defaults let list endpoints omit them.
    move_count: int = 0
    time_in_current_status_seconds: Optional[int] = None
    is_scope_creep: bool = False


class ReleaseChangeReleaseHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_id: int
    from_release_id: Optional[int]
    to_release_id: Optional[int]
    moved_at: datetime
    moved_by: Optional[int]
    notes: Optional[str]


class ReleaseChangeStatusHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    change_id: int
    from_status: Optional[str]
    to_status: Optional[str]
    changed_at: datetime
    changed_by: Optional[int]
    notes: Optional[str]


from app.api.v1.schemas.version import ImportError  # noqa: E402


class ScopeImportResult(BaseModel):
    created: int
    updated: int
    errors: list[ImportError]
