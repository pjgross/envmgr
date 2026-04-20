# backend/app/api/v1/schemas/release_dependency.py
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ReleaseDependencyCreate(BaseModel):
    depends_on_release_id: int
    kind: str = "deploys_after"
    notes: Optional[str] = None


class ReleaseDependencyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    depends_on_release_id: int
    kind: str
    notes: Optional[str]
    last_dependency_target_date: Optional[datetime]


class ReleaseDependencyAlert(BaseModel):
    dependency_id: int
    depends_on_release_id: int
    depends_on_name: str
    prior_target_date: Optional[datetime]
    current_target_date: Optional[datetime]
    diff_days: int
