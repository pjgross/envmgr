"""Schemas for the release gate readiness verdict.

Mirrors `preflight.py` exactly, including `ok` — see
`release_readiness_service.evaluate` for the rules that populate these.
"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class ReadinessBlocker(BaseModel):
    type: Literal["gate_pending", "gate_failed", "waiver_expired"]
    ref_kind: Literal["gate"]
    ref_id: int
    gate_name: str
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
    ]
    ref_kind: Literal["gate", "evidence"]
    ref_id: int
    gate_name: str
    gate_type: Optional[str] = None
    detail: Optional[str] = None


class ReleaseReadinessResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ok: bool
    release_id: int
    checked_at: datetime
    blockers: list[ReadinessBlocker]
    warnings: list[ReadinessWarning]
