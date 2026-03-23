from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.environment import EnvironmentStatus, EnvironmentSystemStatus
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
    status: EnvironmentSystemStatus = EnvironmentSystemStatus.ACTIVE
    mock_notes: Optional[str] = None


class EnvironmentSystemUpdate(BaseModel):
    status: Optional[EnvironmentSystemStatus] = None
    mock_notes: Optional[str] = None


class EnvironmentSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    system_id: int
    status: EnvironmentSystemStatus
    mock_notes: Optional[str] = None
    system: SystemResponse
