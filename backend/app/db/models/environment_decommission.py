"""B5 — the decommissioning record, its attestations, and the tenant's
checklist vocabulary.

THE ROW STORES FACTS; THE STATE IS COMPUTED. Following A4's
ContentionEscalation: there is no status column, so there is nothing to
invalidate when a notice period elapses, and no scheduler to run.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentDecommission(Base):
    """One decommission attempt. At most one LIVE row per environment —
    enforced in the service, not by a partial unique index, which would be
    inert on SQLite (the same call B3a's group-name uniqueness made)."""

    __tablename__ = "environment_decommission"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    # Required: a decommission with no stated reason is not an audit record.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    warned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # warned_at + the tenant's decommission_notice_days. The initiator may move
    # it LATER, never earlier — an initiator who could shorten the notice would
    # make §2.12's five-day warning advisory, and the booking refusal derives
    # from this column.
    scheduled_teardown_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    initiated_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)

    # The extension block. ONE extension per decommission (spec §4.3): a second
    # request is refused, pointing at cancel-and-re-raise.
    extension_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    extension_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extension_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extension_decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    # NULL means "not decided" — which is branch 3 of the computed state.
    extension_granted: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )

    torn_down_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    torn_down_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )

    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user.id"), nullable=True
    )
    cancel_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentDecommission(id={self.id}, "
            f"environment_id={self.environment_id})>"
        )


class EnvironmentDecommissionAttestation(Base):
    """A human confirming a step happened. IMMUTABLE — no deleted_at, following
    BookingStatusHistory. A mistaken signature is corrected by cancelling the
    decommission, not by editing the record."""

    __tablename__ = "environment_decommission_attestation"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    decommission_id: Mapped[int] = mapped_column(
        ForeignKey("environment_decommission.id"), nullable=False, index=True
    )
    # A PLAIN STRING, NOT AN FK to environment_decommission_step: an attestation
    # must still read correctly after its step definition is retired. Same rule
    # as A2's environment_group_id being provenance rather than a live link.
    step_key: Mapped[str] = mapped_column(String(100), nullable=False)
    signed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    signed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Snapshot id, ticket, runbook link — the evidence a register can honestly
    # hold. Free text on purpose; it is not parsed.
    reference: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "decommission_id", "step_key", name="uq_decommission_step"
        ),
    )


class EnvironmentDecommissionStep(Base):
    """The tenant's checklist vocabulary, shaped like EnvironmentTier and
    BookingType."""

    __tablename__ = "environment_decommission_step"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
