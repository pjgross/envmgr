from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

FailureBehaviour = Literal["block", "warn", "accept_with_exception"]


class GateTypeCreate(BaseModel):
    # extra="forbid" so a typo'd key is a 422 rather than a silent drop — the
    # POST /projects and POST /tenant/lifecycle-templates class of bug.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=150)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    failure_behaviour: FailureBehaviour = "warn"
    expected_evidence: list[str] = Field(default_factory=list)
    requires_deployment_link: bool = False
    display_order: int = 0
    is_active: bool = True


class GateTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=150)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=50)
    failure_behaviour: Optional[FailureBehaviour] = None
    expected_evidence: Optional[list[str]] = None
    requires_deployment_link: Optional[bool] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class GateTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    description: Optional[str]
    category: Optional[str]
    failure_behaviour: str
    expected_evidence: list[str]
    requires_deployment_link: bool
    display_order: int
    is_active: bool
