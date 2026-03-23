from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.dependency import DependencyType, DependencySource
from app.api.v1.schemas.system import SystemResponse, SubSystemResponse


# ---------------------------------------------------------------------------
# SystemDependency schemas
# ---------------------------------------------------------------------------


class SystemDependencyCreate(BaseModel):
    to_system_id: int
    dependency_type: DependencyType
    source: DependencySource = DependencySource.MANUAL


class SystemDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_system_id: int
    to_system_id: int
    dependency_type: DependencyType
    source: DependencySource
    tenant_id: int
    to_system: SystemResponse


# ---------------------------------------------------------------------------
# ComponentDependency schemas
# ---------------------------------------------------------------------------


class ComponentDependencyCreate(BaseModel):
    to_subsystem_id: int
    dependency_type: DependencyType
    protocol: Optional[str] = None
    port: Optional[int] = None
    source: DependencySource = DependencySource.MANUAL


class ComponentDependencyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_subsystem_id: int
    to_subsystem_id: int
    dependency_type: DependencyType
    protocol: Optional[str] = None
    port: Optional[int] = None
    source: DependencySource
    tenant_id: int
    to_subsystem: SubSystemResponse


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
