from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Incident(Base):
    __tablename__ = "incident"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    severity: Mapped[str] = mapped_column(String(2), nullable=False)  # P1|P2|P3|P4

    lifecycle_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # current lifecycle state

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    environment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("environment.id"), nullable=True)
    deployment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deployment.id"), nullable=True)
    release_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release.id"), nullable=True)       # causal
    fix_release_id: Mapped[Optional[int]] = mapped_column(ForeignKey("release.id"), nullable=True)   # fix
    system_id: Mapped[Optional[int]] = mapped_column(ForeignKey("system.id"), nullable=True)
    subsystem_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subsystem.id"), nullable=True)

    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    external_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_incident_tenant_status", "tenant_id", "status"),
        Index("ix_incident_tenant_release", "tenant_id", "release_id"),
        Index("ix_incident_tenant_system", "tenant_id", "system_id"),
        Index("ix_incident_tenant_source_ref", "tenant_id", "source", "external_ref"),
    )


class IncidentStatusHistory(Base):
    __tablename__ = "incident_status_history"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_state: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_state: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
