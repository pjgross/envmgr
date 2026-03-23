from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class VersionCreate(BaseModel):
    subsystem_id: int
    build_id: str
    version_label: str
    installed_at: Optional[datetime] = None  # if None, use server default


class VersionResponse(BaseModel):
    """
    Response schema for a version row.

    ``subsystem_name`` is resolved from the loaded ``subsystem`` relationship and
    cannot be populated by Pydantic's standard ``model_validate`` / ORM mode alone.
    Always construct instances via ``from_orm_with_name``.
    """

    id: int
    environment_id: int
    subsystem_id: int
    subsystem_name: str
    build_id: str
    version_label: str
    installed_at: datetime
    tenant_id: int
    created_at: datetime

    @classmethod
    def from_orm_with_name(cls, obj) -> "VersionResponse":
        """Build response, pulling subsystem_name from the eagerly-loaded relationship."""
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
