"""Acknowledgement that a booking's usage-agreement gap has been seen.

ONLY THE ACKNOWLEDGEMENT IS STORED. The gap itself is computed by
agreement_gap_service, so adding the missing agreement makes the warning
disappear with nothing to invalidate — no stored flag can drift from the
usage_agreement table it summarises.

Keyed on booking_id alone: unlike a conflict, which is pairwise, a gap is a
property of one booking.

ACCEPTED WRINKLE: a booking's dates are editable, so acknowledging "outside
the agreed window" and then moving the dates leaves a stale ack suppressing a
warning it was never given for. Conflicts have the same property and accept
it; building ack-invalidation would add a state machine nobody has asked for.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UsageAgreementAck(Base):
    __tablename__ = "usage_agreement_ack"
    __table_args__ = (
        # One booking, one answer. `booking.id` is globally unique, so the
        # constraint needs no tenant_id to be correct — and leaving it out is
        # what makes a second row impossible rather than merely unlikely.
        UniqueConstraint("booking_id", name="uq_agreement_ack_booking"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("booking.id"), nullable=False, index=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # NOT NULL, deliberately unlike booking_conflict_ack's nullable pair. There
    # the row may exist before an answer does (`willing_to_share IS NULL` means
    # "asked, not answered", and has_unacknowledged_conflicts reads it as
    # unacknowledged). Here the row's EXISTENCE is the acknowledgement, so an
    # ack with no author or no timestamp is not a weaker record — it is a
    # meaningless one, and "who accepted this risk, and when" is the only thing
    # the table is for.
    acknowledged_by: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False
    )
    acknowledged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
