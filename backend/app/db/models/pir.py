from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PIR(Base):
    """One review per release: a summary and a status, and nothing else.

    The five free-text columns (`root_cause`, `what_went_well`,
    `what_went_wrong`, `action_plan`) and the single `incident_id` were
    retired by the `pirbackfill` revision. A review that found six things could
    not say which root cause belonged to which failure, and the incident link
    was 1:1 in both directions when one incident routinely exposes two distinct
    process failures. Both now live in `pir_finding.py`.
    """

    __tablename__ = "pir"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")  # draft | complete
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_tenant_release", "tenant_id", "release_id"),
    )
