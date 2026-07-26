from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Release(Base):
    __tablename__ = "release"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_type: Mapped[str] = mapped_column(String(50), nullable=False)
    release_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="project")
    parent_release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", use_alter=True, name="fk_release_parent"),
        nullable=True,
        index=True,
    )
    # FK to release_template added via migration; plain Integer here for SQLite test compat
    template_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    lifecycle_template_id: Mapped[int] = mapped_column(
        ForeignKey("lifecycle_template.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(100), nullable=False, default="draft")
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raised_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    scope_deadline: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    lifecycle_template = relationship("LifecycleTemplate")


class ReleaseStatusHistory(Base):
    __tablename__ = "release_status_history"

    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    from_state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    to_state: Mapped[str] = mapped_column(String(100), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
