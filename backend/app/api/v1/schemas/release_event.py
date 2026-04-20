# backend/app/api/v1/schemas/release_event.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseEventTypeCreate(BaseModel):
    name: str
    display_color: Optional[str] = None


class ReleaseEventTypeUpdate(BaseModel):
    name: Optional[str] = None
    display_color: Optional[str] = None


class ReleaseEventTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    display_color: Optional[str]
    is_system: bool


class ReleaseEventCreate(BaseModel):
    event_type_id: int
    description: str
    occurred_at: Optional[datetime] = None  # defaults to now in service


class ReleaseEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    event_type_id: int
    description: str
    occurred_at: datetime
    recorded_by: int
