from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.infrastructure_component import (
    InfrastructureComponentSource,
    InfrastructureComponentType,
)


class InfrastructureComponentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    component_type: InfrastructureComponentType = InfrastructureComponentType.OTHER
    provider: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None
    source: InfrastructureComponentSource = InfrastructureComponentSource.MANUAL
    external_id: Optional[str] = None
    custom_fields: Optional[dict] = None
    tags: Optional[dict] = None


class InfrastructureComponentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    component_type: Optional[InfrastructureComponentType] = None
    provider: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None
    source: Optional[InfrastructureComponentSource] = None
    external_id: Optional[str] = None
    custom_fields: Optional[dict] = None
    tags: Optional[dict] = None


class InfrastructureComponentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    component_type: InfrastructureComponentType
    provider: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None
    source: InfrastructureComponentSource
    external_id: Optional[str] = None
    custom_fields: Optional[dict] = None
    tags: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class InfrastructureComponentSummary(BaseModel):
    """Lightweight shape embedded in CR responses and env-subsystem host rows."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    component_type: InfrastructureComponentType
    provider: Optional[str] = None
    region: Optional[str] = None


class HostAttachment(BaseModel):
    """Input shape for PUT /environments/{env_id}/subsystems/{sub_id}/hosts body."""
    infrastructure_component_id: int
    role: Optional[str] = Field(default=None, max_length=50)


class EnvironmentSubSystemHostResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_subsystem_id: int
    infrastructure_component_id: int
    infrastructure_component: InfrastructureComponentSummary
    role: Optional[str] = None


class EnvironmentSubSystemHostsResponse(BaseModel):
    hosts: list[EnvironmentSubSystemHostResponse]
