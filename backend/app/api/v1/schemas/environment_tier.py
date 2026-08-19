from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentTierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: int = 0
    is_active: bool = True
    # B5 — per-tier idle override. NULL (the default) means "use the
    # tenant's environment_lifecycle_policy.idle_threshold_days".
    idle_threshold_days: Optional[int] = Field(default=None, ge=1, le=3650)


class EnvironmentTierUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    color: Optional[str] = Field(default=None, max_length=7)
    display_order: Optional[int] = None
    is_active: Optional[bool] = None
    # Unlike the other nullable fields on this schema (description, color),
    # which the service only ever SETS (never clears — see
    # environment_tier_service.update_tier's `is not None` checks), an
    # explicit null here must be honoured: it is how an admin removes a
    # tier's override and falls back to the tenant default. The service reads
    # this via `model_fields_set`, the same pattern environment_service uses
    # for `expires_at`.
    idle_threshold_days: Optional[int] = Field(default=None, ge=1, le=3650)


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
    idle_threshold_days: Optional[int] = None
