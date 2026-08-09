"""A formal request for a human to decide a contention.

ONLY THE ASKING AND THE ANSWER ARE STORED. The verdict is computed by
contention_service, and this record's own STATE is computed too — open,
answered and expired are facts about `respond_by` and `decided_at`, not a
column something has to write. That is why A4 needs no background job.

Keyed on the UNORDERED pair: a conflict is symmetric, so (A,B) and (B,A) are
one contention. Without normalisation plus the unique constraint, both owners
escalating the same clash create two records with two owners and two clocks.

A4 NEVER MOVES A BOOKING. `decision_yields_booking_id` records which booking a
human said should give way; acting on it is the owning team's job, through the
ordinary transition path. That matters for A2 group bookings — the team moves
their whole group atomically, and A4 never reaches inside one.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentionEscalation(Base):
    __tablename__ = "contention_escalation"
    __table_args__ = (
        # `booking.id` is globally unique, so the pair alone is correct without
        # tenant_id — and leaving it out is what makes a second row impossible
        # rather than merely unlikely.
        UniqueConstraint("booking_id", "other_booking_id", name="uq_contention_pair"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    # NORMALISED: booking_id < other_booking_id. See normalise_pair.
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("booking.id"), nullable=False, index=True
    )
    other_booking_id: Mapped[int] = mapped_column(
        ForeignKey("booking.id"), nullable=False, index=True
    )
    escalated_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    # REQUIRED: an escalation with no deadline can never expire, which would
    # remove the half of §2.12 that makes escalation time-bound.
    respond_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_yields_booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("booking.id"), nullable=True
    )
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
