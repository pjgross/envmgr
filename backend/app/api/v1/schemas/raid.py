from datetime import datetime
from typing import Optional, Any, Literal

from pydantic import BaseModel, Field, ConfigDict


class RaidItemCreate(BaseModel):
    item_type: Literal["risk", "assumption", "issue", "dependency"]
    title: str = Field(..., max_length=500)
    description: Optional[str] = None
    owner_id: Optional[int] = None
    target_date: Optional[datetime] = None
    review_date: Optional[datetime] = None
    probability: Optional[int] = Field(None, ge=1)
    impact: Optional[int] = Field(None, ge=1)
    response_strategy: Optional[str] = Field(None, max_length=20)
    mitigation_plan: Optional[str] = None
    contingency_plan: Optional[str] = None
    evidence: Optional[str] = None
    resolution_plan: Optional[str] = None
    direction: Optional[str] = Field(None, max_length=20)
    counterparty: Optional[str] = Field(None, max_length=200)
    due_date: Optional[datetime] = None
    release_dependency_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None


class RaidItemUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[int] = None
    target_date: Optional[datetime] = None
    review_date: Optional[datetime] = None
    probability: Optional[int] = None
    impact: Optional[int] = None
    response_strategy: Optional[str] = None
    mitigation_plan: Optional[str] = None
    contingency_plan: Optional[str] = None
    validation_status: Optional[str] = None
    evidence: Optional[str] = None
    resolution_plan: Optional[str] = None
    escalated: Optional[bool] = None
    direction: Optional[str] = None
    counterparty: Optional[str] = None
    due_date: Optional[datetime] = None
    at_risk: Optional[bool] = None
    custom_fields: Optional[dict[str, Any]] = None


class RaidPromotePayload(BaseModel):
    target_type: Literal["risk", "issue"]


class RaidItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    item_type: str
    seq: int
    ref_code: str = ""          # computed by the service mapper
    title: str
    description: Optional[str] = None
    status: str
    owner_id: Optional[int] = None
    raised_by: int
    raised_at: datetime
    target_date: Optional[datetime] = None
    review_date: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    probability: Optional[int] = None
    impact: Optional[int] = None
    severity: Optional[int] = None   # computed
    rag: Optional[str] = None        # computed
    response_strategy: Optional[str] = None
    mitigation_plan: Optional[str] = None
    contingency_plan: Optional[str] = None
    validation_status: Optional[str] = None
    validated_at: Optional[datetime] = None
    evidence: Optional[str] = None
    resolution_plan: Optional[str] = None
    resolved_at: Optional[datetime] = None
    escalated: bool = False
    direction: Optional[str] = None
    counterparty: Optional[str] = None
    due_date: Optional[datetime] = None
    at_risk: bool = False
    release_dependency_id: Optional[int] = None
    promoted_from_id: Optional[int] = None
    custom_fields: Optional[dict[str, Any]] = None
