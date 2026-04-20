# backend/app/api/v1/schemas/release_change.py
from typing import Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ReleaseChangeCreate(BaseModel):
    external_key: Optional[str] = Field(None, max_length=50)
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    change_kind: str  # story | defect
    external_status: Optional[str] = Field(None, max_length=100)
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseChangeUpdate(BaseModel):
    external_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    external_status: Optional[str] = None
    system_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None


class ReleaseChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
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
