"""Schemas for gate evidence — a reference vouching for a gate.

`kind` is free text, not an enum: the UI offers a gate type's
`expected_evidence` entries as choices, but an unlisted kind is accepted and
simply satisfies no expectation (see gate_evidence_service.add_evidence).
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class GateEvidenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(..., max_length=150)
    label: str = Field(..., max_length=250)
    url: Optional[str] = Field(None, max_length=1000)
    notes: Optional[str] = None
    deployment_id: Optional[int] = None


class GateEvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gate_id: int
    kind: str
    label: str
    url: Optional[str]
    notes: Optional[str]
    deployment_id: Optional[int]
    added_by: int
    created_at: datetime
    # Required, no default — deliberately. A defaulted bool renders `False` at
    # any construction site that forgets to set it, which is how a field ships
    # permanently (and silently) wrong; see gate_evidence_service.stale_evidence_ids
    # and releases.py's _evidence_to_read, the only two places this is computed.
    is_stale: bool
