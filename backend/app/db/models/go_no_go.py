"""Phase 9 C3 — the Go/No-Go decision record.

Four tables that change together. NOTHING HERE REFUSES ANYTHING: C3 records a
decision a human took; it does not gate transitions, deployments or can-deploy.
"""
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Fixed vocabulary, NOT tenant-configurable — the three outcomes are what
# §2.11 names, and a report that could not tell a go from a no-go would be
# useless. The PERSPECTIVES are the configurable part, not the verdicts.
OUTCOME_VALUES = ("go", "conditional_go", "no_go")


class GoNoGoPerspective(Base):
    """What a signatory is attesting — seeded Quality / Process / Acceptance.

    Tenant-configurable, so NOTHING may assume a given perspective exists.
    """

    __tablename__ = "go_no_go_perspective"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_go_no_go_perspective_tenant_name"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class GoNoGoDecision(Base):
    """One meeting. APPEND-ONLY: no update path, no deleted_at.

    A wrong decision is superseded by recording another, the same escape hatch
    A4 gives a wrong contention owner. An editable record with a frozen
    snapshot is a contradiction — the snapshot would describe a decision whose
    text had since changed.
    """

    __tablename__ = "go_no_go_decision"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    chaired_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    # Attendance is not sign-off: a list of user ids, no verdict attached.
    attendees: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    # THE FROZEN SNAPSHOT. This is the one place in this codebase that STORES
    # what it elsewhere computes on read, and it is deliberate: an audit record
    # that silently rewrites itself when a gate later passes is evidence of
    # nothing. Captured server-side at RECORD time (not at decided_at, which
    # may be backdated and whose verdict is not reconstructible).
    snapshot_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    snapshot_blockers: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    snapshot_warnings: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    snapshot_reversibility: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    snapshot_rehearsal_state: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)


class GoNoGoSignoff(Base):
    """One signatory's verdict on one perspective.

    The decision's OUTCOME is not a fold of these: `outcome='go'` beside a
    `no_go` sign-off is legal and is exactly what §2.11's "dissents" means.
    Two DIFFERENT people may sign the same perspective — two test leads may
    both attest quality — so "is Quality signed" asks whether ANY sign-off
    exists for it.
    """

    __tablename__ = "go_no_go_signoff"
    __table_args__ = (
        UniqueConstraint(
            "decision_id", "perspective_id", "user_id", name="uq_go_no_go_signoff_unique"
        ),
    )

    decision_id: Mapped[int] = mapped_column(
        ForeignKey("go_no_go_decision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    perspective_id: Mapped[int] = mapped_column(
        ForeignKey("go_no_go_perspective.id"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    dissent_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class GoNoGoCondition(Base):
    """What a conditional go is conditional on.

    The ONE mutable part of an append-only record: closing a condition records
    a later FACT ABOUT the decision, it does not rewrite what was decided.
    """

    __tablename__ = "go_no_go_condition"

    decision_id: Mapped[int] = mapped_column(
        ForeignKey("go_no_go_decision.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    owner_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    met_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    met_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
