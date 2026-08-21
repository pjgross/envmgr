"""Schemas for the release gate readiness verdict.

Mirrors `preflight.py` exactly, including `ok` — see
`release_readiness_service.evaluate` for the rules that populate these.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReadinessBlocker(BaseModel):
    type: Literal[
        "gate_pending",
        "gate_failed",
        "waiver_expired",
        "rollback_plan_missing",
        "rollback_plan_unagreed",
        "rehearsal_missing",
        "rehearsal_stale",
    ]
    ref_kind: Literal["gate", "system"]
    ref_id: int
    # No gate backs a rollback finding — set explicitly (None) at every
    # rollback construction site rather than relying on this default, which
    # is how C2 shipped a field permanently wrong at a site that forgot it.
    gate_name: Optional[str] = None
    gate_type: Optional[str] = None
    detail: Optional[str] = None


class ReadinessWarning(BaseModel):
    type: Literal[
        "gate_waived",
        "gate_waived_no_record",
        "gate_untyped",
        "gate_pending",
        "gate_failed",
        "evidence_missing",
        "evidence_stale",
        "rollback_plan_missing",
        "rollback_plan_unagreed",
        "rehearsal_missing",
        "rehearsal_stale",
        "rollback_irreversible",
        "rollback_lossy",
    ]
    ref_kind: Literal["gate", "evidence", "system"]
    ref_id: int
    gate_name: Optional[str] = None
    gate_type: Optional[str] = None
    detail: Optional[str] = None


class ReleaseReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: bool
    release_id: int
    checked_at: datetime
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]
    # The worst reversibility across the release's rollback plans, or None if
    # there are none. Computed by rollback_plan_service.rollup — see there.
    reversibility: Optional[str] = None
