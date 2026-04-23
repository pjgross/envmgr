from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Build(Base):
    __tablename__ = "build"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subsystem_id", "git_sha", "build_number",
            name="uq_build_tenant_sub_sha_num",
        ),
        Index("ix_build_tenant_subsystem", "tenant_id", "subsystem_id"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    git_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    build_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    commit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    build_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    build_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_tickets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pipeline_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
