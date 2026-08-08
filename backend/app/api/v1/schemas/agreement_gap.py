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
    # The author's NAME, travelling with the row the way `owner_username` and
    # `ReleaseSystemRead.system_name` do. `acknowledged_by` is a user id and
    # this codebase renders entities by name, never `#N`; resolving it in the
    # browser would mean looking it up in the capped tenant-users collection,
    # where a name past the cap is information LOST, not merely hidden.
    #
    # REQUIRED, with no default, on purpose: this schema is built by
    # `model_validate(ack)` at every site, an ORM ack has no such attribute, and
    # Pydantic silently defaults a missing non-column attribute rather than
    # raising — which is how A1 shipped a response field that rendered null at
    # four of five construction sites with a green suite. Required turns that
    # into a ValidationError, so the only way to build one is
    # `bookings.py::_ack_read`, which resolves the name itself.
    #
    # Nullable in VALUE, though: a user row can go missing (hard-deleted in a
    # repair, or an id that no longer resolves), and "Acknowledged on <when>"
    # with no name is the right answer then — never the id.
    acknowledged_by_username: Optional[str]


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
