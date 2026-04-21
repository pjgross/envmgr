"""Immutable history tables for ReleaseChange (scope item) lifecycle events.

Two siblings, both following the BookingStatusHistory pattern:
- ReleaseChangeReleaseHistory  — every release_id change (create, move, unlink).
- ReleaseChangeStatusHistory   — every external_status change.

Rows are immutable: no deleted_at, no update paths. Reserves release_id FKs
as ON DELETE SET NULL so an audit row survives deletion of either release.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseChangeReleaseHistory(Base):
    __tablename__ = "release_change_release_history"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("release_change.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True
    )
    to_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True
    )
    moved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    moved_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ReleaseChangeStatusHistory(Base):
    __tablename__ = "release_change_status_history"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    change_id: Mapped[int] = mapped_column(
        ForeignKey("release_change.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    changed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
