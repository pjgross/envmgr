from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PIR(Base):
    __tablename__ = "pir"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incident.id"), nullable=True, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_went_well: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_went_wrong: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")  # draft | complete
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_tenant_release", "tenant_id", "release_id"),
        Index("ix_pir_tenant_incident", "tenant_id", "incident_id"),
    )
