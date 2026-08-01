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
    build_sha_short: Optional[str] = None
    environment_id: int
    environment_name: Optional[str] = None
    release_id: Optional[int]
    release_name: Optional[str] = None
    change_request_id: int
    change_request_title: Optional[str] = None
    # `str`, not `UUID`, because that is what the column can actually hold:
    # `String(36)`, with `deployment_service` storing and comparing
    # `str(payload.event_id)`. Declaring UUID here asserted something the
    # storage layer never enforced, and the response model is applied per row
    # while serialising the page — so a single row whose id did not parse
    # returned 500 for the WHOLE list rather than one odd-looking cell.
    # `DeploymentWebhookPayload.event_id` above is still a UUID, so this does
    # not loosen what the supported ingest path accepts.
    event_id: str
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
