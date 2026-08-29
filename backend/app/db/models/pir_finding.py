"""What a post-implementation review actually found, and what is being done about it.

A PIR is one row per release (`pir`) holding a summary. Everything the review
FOUND lives here: a `PirFinding` is one thing that went well or one thing that
went wrong, and a `PirAction` is a process fix hanging off a finding.

Two rules worth keeping straight:

- Actions hang off a FINDING, not off the PIR, so "which failure is this fix
  for" is structural rather than prose. They are allowed on a `went_well`
  finding too — "codify this in the release template" is a real PIR outcome.
- There is deliberately no denormalised `release_id`/`pir_id` on `PirAction`.
  The cross-release worklist joins action -> finding -> pir -> release. A
  denormalised copy is one more thing that can disagree with the row it was
  copied from.

`PirFindingIncident` is the citation: an incident, raised by the ITIL process or
by monitoring, offered as EVIDENCE that a process failed. The PIR fixes the
process that let the incident reach production; it does not fix the incident.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

FINDING_KINDS = {"went_well", "went_wrong"}
ACTION_STATUSES = {"open", "in_progress", "done", "cancelled"}
# The two statuses that stamp `closed_at`. Leaving either one clears it again —
# a reopened action has no closing date, and a stale one would be read as a
# closure that happened.
CLOSED_ACTION_STATUSES = {"done", "cancelled"}
# The statuses an overdue due date can still be overdue ON. A done or cancelled
# action is not overdue however far past its date it sits.
LIVE_ACTION_STATUSES = {"open", "in_progress"}


class PirFinding(Base):
    __tablename__ = "pir_finding"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    pir_id: Mapped[int] = mapped_column(
        ForeignKey("pir.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # went_well | went_wrong
    seq: Mapped[int] = mapped_column(Integer, nullable=False)      # per (pir_id, kind)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Meaningful on a went_wrong finding. Nothing refuses one on a went_well
    # finding: a half-useful note on a thing that worked is not worth a 422.
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_finding_tenant_pir", "tenant_id", "pir_id"),
    )


class PirAction(Base):
    __tablename__ = "pir_action"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # per finding_id
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_action_tenant_finding", "tenant_id", "finding_id"),
        Index("ix_pir_action_tenant_status", "tenant_id", "status"),
    )


class PirFindingIncident(Base):
    """An incident offered as evidence for a finding. Hard-deleted: removing a
    citation is a correction, not history — the junction-record convention in
    CLAUDE.md."""

    __tablename__ = "pir_finding_incident"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id"), nullable=False, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("finding_id", "incident_id", name="uq_pir_finding_incident"),
        Index("ix_pir_finding_incident_tenant_incident", "tenant_id", "incident_id"),
    )
