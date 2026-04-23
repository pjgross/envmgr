from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.build import BuildPayload


class DeploymentWebhookPayload(BaseModel):
    """Body of POST /api/v1/webhooks/deployment."""
    event_id: UUID
    system_slug: str
    subsystem_slug: str
    environment_slug: str
    status: str
    deployed_at: datetime
    release_id: Optional[int] = None
    change_request_id: Optional[int] = None
    deployer_name: Optional[str] = None
    build: BuildPayload
    deployment_custom_fields: dict[str, Any] = Field(default_factory=dict)


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    build_id: int
    environment_id: int
    release_id: Optional[int]
    change_request_id: int
    event_id: UUID
    deployer_name: Optional[str]
    deployed_at: datetime
    completed_at: Optional[datetime]
    status: str
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeploymentIngestResult(BaseModel):
    deployment_id: int
    build_id: int
    change_request_id: int
    replayed: bool


class DeploymentLinkChangeRequest(BaseModel):
    change_request_id: int
