from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentTierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: int = 0
    is_active: bool = True


class EnvironmentTierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class EnvironmentTierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    color: Optional[str] = None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
