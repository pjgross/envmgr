from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class VersionCreate(BaseModel):
    subsystem_id: int
    build_id: str
    version_label: str
    installed_at: Optional[datetime] = None  # if None, use server default


class VersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    subsystem_id: int
    subsystem_name: str  # populated manually from subsystem.name
    build_id: str
    version_label: str
    installed_at: datetime
    tenant_id: int
    created_at: datetime

    @classmethod
    def from_orm_with_name(cls, obj) -> "VersionResponse":
        """Build response, pulling subsystem_name from relationship."""
        return cls(
            id=obj.id,
            environment_id=obj.environment_id,
            subsystem_id=obj.subsystem_id,
            subsystem_name=obj.subsystem.name if obj.subsystem else "",
            build_id=obj.build_id,
            version_label=obj.version_label,
            installed_at=obj.installed_at,
            tenant_id=obj.tenant_id,
            created_at=obj.created_at,
        )


class ImportError(BaseModel):
    row: int
    field: str
    message: str


class ImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[ImportError]
