from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field


class PipelineStep(BaseModel):
    name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class BuildPayload(BaseModel):
    """Nested block inside the deployment webhook payload."""
    git_sha: str = Field(..., max_length=64)
    git_branch: Optional[str] = Field(None, max_length=255)
    build_number: Optional[str] = Field(None, max_length=80)
    commit_timestamp: datetime
    build_started_at: Optional[datetime] = None
    build_finished_at: Optional[datetime] = None
    jira_tickets: list[str] = Field(default_factory=list)
    pipeline_steps: list[PipelineStep] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    subsystem_id: int
    release_id: Optional[int]
    git_sha: str
    git_branch: Optional[str]
    build_number: Optional[str]
    commit_timestamp: datetime
    build_started_at: Optional[datetime]
    build_finished_at: Optional[datetime]
    jira_tickets: list[str]
    pipeline_steps: list[PipelineStep]
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
