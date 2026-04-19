# backend/app/api/v1/schemas/release_system.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseSystemCreate(BaseModel):
    system_id: int
    role: str  # 'changing' | 'regression' | 'config_only'
    deployment_date: Optional[datetime] = None


class ReleaseSystemUpdate(BaseModel):
    role: Optional[str] = None
    deployment_date: Optional[datetime] = None


class ReleaseSystemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    system_id: int
    role: str
    deployment_date: Optional[datetime]
