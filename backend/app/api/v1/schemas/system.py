from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

from app.db.models.system import ComponentType


class SystemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    github_repository_url: Optional[str] = None
    custom_fields: Optional[dict] = None


class SystemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    github_repository_url: Optional[str] = None
    custom_fields: Optional[dict] = None


class SystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    tenant_id: int
    github_repository_url: Optional[str] = None
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class SubSystemCreate(BaseModel):
    name: str
    description: Optional[str] = None
    component_type: ComponentType = ComponentType.OTHER
    technology: Optional[str] = None
    custom_fields: Optional[dict] = None


class SubSystemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    component_type: Optional[ComponentType] = None
    technology: Optional[str] = None
    custom_fields: Optional[dict] = None


class SubSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    component_type: ComponentType
    technology: Optional[str] = None
    system_id: int
    tenant_id: int
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
