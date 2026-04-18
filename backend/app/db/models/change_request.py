import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean, Integer
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ChangeType(str, enum.Enum):
    CONFIGURATION = "configuration"
    INFRASTRUCTURE = "infrastructure"
    CODE_DEPLOYMENT = "code_deployment"


class ChangeRequest(Base):
    """A change request (TECR) raised against a subsystem in a specific environment.

    Changes follow a configurable lifecycle (via `lifecycle_id` → LifecycleTemplate
    with entity_type='change_request'). They may declare an outage window to block
    out the environment during the change; the unified environment schedule shows
    outage periods alongside bookings.
    """

    __tablename__ = "change_request"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Current lifecycle state (key matching LifecycleTemplate.definition.states[].key)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")

    lifecycle_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    # CRs are raised on a sub-resource (subsystem), not the environment as a whole
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    # Environment link drives schedule-view aggregation
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    # Placeholder for Phase 3 Release model — no FK until that table exists.
    release_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    has_outage: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    outage_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outage_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    scheduled_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scheduled_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    raised_by: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    lifecycle = relationship("LifecycleTemplate")
    subsystem = relationship("SubSystem")
    environment = relationship("Environment")


class ChangeHistory(Base):
    """Immutable audit row for a change request.

    Mirrors BookingStatusHistory for state transitions; `field_name`/`old_value`/
    `new_value` accommodate general field-level audit entries (both forms can
    coexist in the same table — service layer chooses which fields to set).
    """

    __tablename__ = "change_history"

    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_request.id"), nullable=False, index=True
    )
    from_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    field_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    old_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    changed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # No deleted_at — history rows are immutable audit records
