import enum
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, ForeignKey, Boolean, Integer, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.environment import Environment
    from app.db.models.infrastructure_component import InfrastructureComponent


class ChangeType(str, enum.Enum):
    CONFIGURATION = "configuration"
    INFRASTRUCTURE = "infrastructure"
    CODE_DEPLOYMENT = "code_deployment"


class ChangeRequest(Base):
    """A change request (TECR).

    A CR can target any combination of environments (via
    `change_request_environment`) and infrastructure components (via
    `change_request_host`); at least one target is required. When a host is
    the target, affected environments are derived through the
    `environment_subsystem_host` junction and exposed to consumers as
    `derived_environment_ids`.

    `subsystem_id` is optional — CRs raised against an environment may
    narrow to a single subsystem; host-level / platform CRs leave it null.
    """

    __tablename__ = "change_request"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")

    lifecycle_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    subsystem_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("subsystem.id"), nullable=True, index=True
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

    lifecycle = relationship("LifecycleTemplate")
    subsystem = relationship("SubSystem")
    environments: Mapped[list["ChangeRequestEnvironment"]] = relationship(
        "ChangeRequestEnvironment",
        back_populates="change_request",
        lazy="select",
        cascade="all, delete-orphan",
    )
    hosts: Mapped[list["ChangeRequestHost"]] = relationship(
        "ChangeRequestHost",
        back_populates="change_request",
        lazy="select",
        cascade="all, delete-orphan",
    )


class ChangeRequestEnvironment(Base):
    """Junction binding a ChangeRequest to each environment it targets."""

    __tablename__ = "change_request_environment"

    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "change_request_id", "environment_id", name="uq_cr_environment"
        ),
    )

    change_request: Mapped["ChangeRequest"] = relationship(
        "ChangeRequest", back_populates="environments"
    )
    environment: Mapped["Environment"] = relationship("Environment")


class ChangeRequestHost(Base):
    """Junction binding a ChangeRequest to each host it targets directly."""

    __tablename__ = "change_request_host"

    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_request.id", ondelete="CASCADE"), nullable=False, index=True
    )
    infrastructure_component_id: Mapped[int] = mapped_column(
        ForeignKey("infrastructure_component.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "change_request_id",
            "infrastructure_component_id",
            name="uq_cr_host",
        ),
    )

    change_request: Mapped["ChangeRequest"] = relationship(
        "ChangeRequest", back_populates="hosts"
    )
    infrastructure_component: Mapped["InfrastructureComponent"] = relationship(
        "InfrastructureComponent"
    )


class ChangeHistory(Base):
    """Immutable audit row for a change request."""

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
