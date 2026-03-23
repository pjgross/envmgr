from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.dependency import DependencyType, DependencySource, DependencyDirection
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


class SystemDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_system_id: int
    to_system_id: int
    dependency_type: DependencyType
    direction: DependencyDirection
    source: DependencySource
    tenant_id: int
    to_system: SystemResponse
    from_system: Optional[SystemBase] = None
    is_incoming: bool = False


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
    tenant_id: int
    to_subsystem: SubSystemResponse
    from_subsystem: Optional[SubSystemBase] = None
    is_incoming: bool = False


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


class VerifyResponse(BaseModel):
    environment_id: int
    total_dependencies: int
    satisfied_count: int
    mocked_count: int
    missing_count: int
    systems: list[SystemVerifyResult]
