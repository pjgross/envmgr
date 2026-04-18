from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.dependency import DependencyType, DependencySource, DependencyDirection, HttpMethod
from app.api.v1.schemas.system import SystemResponse, SubSystemResponse


# ---------------------------------------------------------------------------
# Nested base schemas for dependency responses
# ---------------------------------------------------------------------------


class SystemBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None


class SubSystemBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    system_id: int


# ---------------------------------------------------------------------------
# SystemDependency schemas
# ---------------------------------------------------------------------------


class SystemDependencyCreate(BaseModel):
    to_system_id: int
    dependency_type: DependencyType
    direction: DependencyDirection = DependencyDirection.ONE_WAY
    source: DependencySource = DependencySource.MANUAL
    label: Optional[str] = None


class SystemDependencyUpdate(BaseModel):
    dependency_type: Optional[DependencyType] = None
    source: Optional[DependencySource] = None
    direction: Optional[DependencyDirection] = None
    label: Optional[str] = None


class SystemDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_system_id: int
    to_system_id: int
    dependency_type: DependencyType
    direction: DependencyDirection
    source: DependencySource
    label: Optional[str] = None
    tenant_id: int
    to_system: SystemResponse
    from_system: Optional[SystemBase] = None
    is_incoming: bool = False


# ---------------------------------------------------------------------------
# ComponentEndpoint schemas
# ---------------------------------------------------------------------------


class ComponentEndpointCreate(BaseModel):
    http_method: Optional[HttpMethod] = None
    path: str
    description: Optional[str] = None


class ComponentEndpointUpdate(BaseModel):
    http_method: Optional[HttpMethod] = None
    path: Optional[str] = None
    description: Optional[str] = None


class ComponentEndpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dependency_id: int
    http_method: Optional[HttpMethod] = None
    path: str
    description: Optional[str] = None
    tenant_id: int


# ---------------------------------------------------------------------------
# ComponentDependency schemas
# ---------------------------------------------------------------------------


class ComponentDependencyCreate(BaseModel):
    to_subsystem_id: int
    dependency_type: DependencyType
    direction: DependencyDirection = DependencyDirection.ONE_WAY
    protocol: Optional[str] = None
    port: Optional[int] = None
    source: DependencySource = DependencySource.MANUAL
    label: Optional[str] = None


class ComponentDependencyUpdate(BaseModel):
    dependency_type: Optional[DependencyType] = None
    protocol: Optional[str] = None
    port: Optional[int] = None
    source: Optional[DependencySource] = None
    direction: Optional[DependencyDirection] = None
    label: Optional[str] = None


class ComponentDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_subsystem_id: int
    to_subsystem_id: int
    dependency_type: DependencyType
    direction: DependencyDirection
    protocol: Optional[str] = None
    port: Optional[int] = None
    source: DependencySource
    label: Optional[str] = None
    tenant_id: int
    to_subsystem: SubSystemResponse
    from_subsystem: Optional[SubSystemBase] = None
    is_incoming: bool = False
    endpoints: list[ComponentEndpointResponse] = []


# ---------------------------------------------------------------------------
# Verify response schemas
# ---------------------------------------------------------------------------


class DependencyVerifyItem(BaseModel):
    to_system_id: int
    to_system_name: str
    dependency_type: DependencyType
    status: Literal["satisfied", "mocked", "missing"]


class SystemVerifyResult(BaseModel):
    system_id: int
    system_name: str
    dependencies: list[DependencyVerifyItem]


class ComponentVerifyItem(BaseModel):
    from_subsystem_id: int
    from_subsystem_name: str
    to_subsystem_id: int
    to_subsystem_name: str
    dependency_type: DependencyType
    status: Literal["satisfied", "mocked", "missing"]


class VerifyResponse(BaseModel):
    environment_id: int
    total_dependencies: int
    satisfied_count: int
    mocked_count: int
    missing_count: int
    systems: list[SystemVerifyResult]
    component_total: int = 0
    component_satisfied: int = 0
    component_mocked: int = 0
    component_missing: int = 0
    component_dependencies: list[ComponentVerifyItem] = []
