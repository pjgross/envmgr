"""Schemas for acknowledging a usage-agreement gap (A3).

Shaped on `schemas/conflict.py`'s ConflictAckRead/ConflictAckUpsert, the ack
this one is modelled on. The GAP itself is never a schema field here: it is
computed by agreement_gap_service and rendered on the booking, so nothing in
this file can drift from the usage_agreement table.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AgreementGapAckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notes: Optional[str]
    # Non-optional, unlike ConflictAckRead's: the row cannot exist without an
    # author and a timestamp (see the model), and typing them as nullable here
    # would invite a consumer to render "acknowledged by nobody".
    acknowledged_by: int
    acknowledged_at: datetime


class AgreementGapAckUpsert(BaseModel):
    # Pydantic's default is extra="ignore", which would answer {"note": "..."}
    # with a 200 and record notes=null — telling the caller their reasoning was
    # filed while the audit trail holds a blank. That is exactly the
    # POST /tenant/lifecycle-templates silent drop CLAUDE.md records.
    #
    # ConflictAckUpsert, this schema's model, does NOT forbid extras. Nor is
    # forbidding them a settled convention here: only 5 of 45 schema modules do
    # it, and B1's own environment_tier.py and B3a's user_group.py — both newer
    # than ConflictAckUpsert — do not. So this is a local judgement, not
    # house style: with one optional field and a governance audit trail behind
    # it, the whole payload is a misspelling away from being lost.
    model_config = ConfigDict(extra="forbid")

    notes: Optional[str] = None
