from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.environment import EnvironmentStatus
from app.api.v1.schemas.system import SystemResponse


class EnvironmentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    environment_type: str
    status: EnvironmentStatus = EnvironmentStatus.ACTIVE
    custom_fields: Optional[dict] = None


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment_type: Optional[str] = None
    status: Optional[EnvironmentStatus] = None
    custom_fields: Optional[dict] = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    environment_type: str
    status: EnvironmentStatus
    tenant_id: int
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class EnvironmentSystemCreate(BaseModel):
    system_id: int


class EnvironmentSystemUpdate(BaseModel):
    pass  # reserved for future fields


class EnvironmentSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    system_id: int
    system: SystemResponse


class SystemSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class EnvironmentSystemsResponse(BaseModel):
    """Response for GET /environments/{env_id}/systems — includes missing systems."""
    systems: list[EnvironmentSystemResponse]
    missing_systems: list[SystemSummary]


class VersionSummary(BaseModel):
    build_identifier: str
    version_label: str
    installed_at: datetime


class EnvironmentSubsystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    subsystem_id: int
    subsystem_name: str
    component_type: str
    component_type_definition_id: Optional[int] = None
    component_type_definition_name: Optional[str] = None
    technology: Optional[str] = None
    system_id: int
    system_name: str
    is_mocked: bool
    mock_notes: Optional[str] = None
    custom_fields: Optional[dict] = None
    latest_version: Optional[VersionSummary] = None


class EnvironmentSubsystemUpdate(BaseModel):
    is_mocked: Optional[bool] = None
    mock_notes: Optional[str] = None
    component_type_definition_id: Optional[int] = None
    custom_fields: Optional[dict] = None


class EnvSubsystemNode(BaseModel):
    """Subsystem node for the environment topology response."""
    id: int
    name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    is_mocked: bool


from app.api.v1.schemas.dependency import ComponentDependencyResponse  # noqa: E402


class EnvironmentTopologyResponse(BaseModel):
    environment_id: int
    subsystems: list[EnvSubsystemNode]
    dependencies: list[ComponentDependencyResponse]
    system_names: dict[str, str]
    outside_subsystems: list[EnvSubsystemNode]
    outside_dependencies: list[ComponentDependencyResponse]
