from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReleaseGate(Base):
    __tablename__ = "release_gate"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Nullable, no backfill: every existing gate stays valid as UNTYPED, and
    # untyped is a state the verdict handles explicitly (it warns, never blocks
    # — no behaviour was declared, so none is invented).
    gate_type_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("gate_type.id"), nullable=True, index=True
    )
    # Nullable because MOST GATES HAVE NO PHASE: Scope Sign-off is created early
    # and belongs to none, and a Go/No-Go gate sits at the end and belongs to
    # none either. Only test sign-off gates carry one.
    test_phase_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("test_phase.id"), nullable=True, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    criteria = relationship(
        "GateCriterion",
        primaryjoin="and_(ReleaseGate.id == foreign(GateCriterion.gate_id), "
                   "GateCriterion.deleted_at.is_(None))",
        lazy="noload",
    )
