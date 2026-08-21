# backend/app/api/v1/schemas/release_gate.py
from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.api.v1.schemas.gate_criterion import GateCriterionRead


class ReleaseGateCreate(BaseModel):
    # extra="forbid" so a typo'd key (e.g. gateTypeId) is a 422 rather than a
    # silent drop — the POST /projects class of bug, and the exact shape of
    # the hole this schema is being extended to close.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., max_length=150)
    due_date: datetime
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None


class ReleaseGateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, max_length=150)
    due_date: Optional[datetime] = None
    # Both keyed on model_fields_set by the service: an OMITTED key means
    # "leave alone", only an explicit null clears it. See update_gate.
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None


class ReleaseGateDecision(BaseModel):
    notes: Optional[str] = None
    # The three fields below only apply to override_gate (a waiver); pass_gate
    # and fail_gate ignore them. expires_at=None means a permanent waiver —
    # a legitimate state, never confused with an expired one.
    expires_at: Optional[datetime] = None
    remediation: Optional[str] = None
    approved_by_user_id: Optional[int] = None


class GateWaiverRead(BaseModel):
    """Task 10c — the waiver record made readable. Mirrors GateWaiver 1:1
    except for `state`, which is computed (see gate_waiver_service.waiver_state)
    rather than stored: there is no status column on the row itself.

    `approved_by_username` is resolved WITHOUT a tenant-qualified join — see
    gate_waiver_service.usernames_for. Under master-admin impersonation the
    approver can legitimately sit outside the gate's own tenant, and a
    User.tenant_id == join would render them as nobody.
    """
    model_config = ConfigDict(from_attributes=True)

    id: int
    reason: str
    approved_by_user_id: int
    approved_by_username: Optional[str]
    expires_at: Optional[datetime]
    remediation: Optional[str]
    created_at: datetime
    state: Literal["live", "expired"]


class ReleaseGateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    release_id: int
    name: str
    due_date: datetime
    status: str
    decided_by: Optional[int]
    decided_at: Optional[datetime]
    decision_notes: Optional[str]
    gate_type_id: Optional[int] = None
    test_phase_id: Optional[int] = None
    criteria: List[GateCriterionRead] = []
    overdue_criterion_count: int = 0
    # Task 10c. Populated only for an `overridden` gate — the current
    # (newest, by id) GateWaiver row for it, or null if none exists (a gate
    # overridden before C2 shipped waivers, or a gate that isn't overridden
    # at all). NOT populated by simply model_validate-ing an ORM ReleaseGate
    # — there is no such attribute on that model — every construction site
    # must set it explicitly. See release_gate_service.list_gates and
    # releases.py's override_gate endpoint, the two sites that do.
    waiver: Optional[GateWaiverRead] = None
