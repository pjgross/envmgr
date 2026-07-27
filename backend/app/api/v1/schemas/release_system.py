# backend/app/api/v1/schemas/release_system.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator

_VALID_ROLES = {"changing", "regression", "config_only"}


class ReleaseSystemCreate(BaseModel):
    system_id: int
    role: str  # 'changing' | 'regression' | 'config_only'
    deployment_date: Optional[datetime] = None

    @field_validator("role")
    @classmethod
    def _valid_role(cls, v):
        if v not in _VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(_VALID_ROLES)}")
        return v


class ReleaseSystemUpdate(BaseModel):
    role: Optional[str] = None
    deployment_date: Optional[datetime] = None


class ReleaseSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    system_id: int
    system_name: Optional[str] = None
    role: str
    deployment_date: Optional[datetime]
