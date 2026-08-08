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
    notes: Optional[str] = None
