from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Integer, DateTime
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReleaseChange(Base):
    __tablename__ = "release_change"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    # Nullable: a scope item with release_id=NULL sits in the backlog, un-assigned
    # to any release until re-prioritised into a new one. On release delete, the
    # FK constraint sets this to NULL so audit history survives.
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_key: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)  # story | defect
    external_status: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    system_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("system.id"), nullable=True, index=True
    )
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Sub-project 3 promotes these to real FKs.
    jira_project_config_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    epic_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
