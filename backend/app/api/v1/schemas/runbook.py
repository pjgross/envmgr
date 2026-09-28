"""Phase 9 C5a — cutover runbook schemas.

Every REQUEST schema declares extra="forbid": an undeclared field on a request
schema is silent data loss here, not a validation error (C6's is_failed,
A4's priority_rank). Update schemas key on model_fields_set — an omitted key
means "leave alone", an explicit null clears a nullable field.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

DeployPattern = Literal["rolling", "blue_green", "canary", "big_bang", "other"]
TaskKind = Literal["task", "check", "deploy", "verification", "ramp"]
TaskStatus = Literal["not_started", "in_progress", "done", "failed", "skipped"]


class RunbookPlanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment_id: int
    name: str = Field(min_length=1, max_length=200)
    anchor_start_at: datetime
    deploy_pattern: Optional[DeployPattern] = None
    notes: Optional[str] = None


class RunbookPlanUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    anchor_start_at: Optional[datetime] = None
    deploy_pattern: Optional[DeployPattern] = None
    notes: Optional[str] = None
