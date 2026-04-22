"""Enterprise release membership workflow.

Stores admission requests (pending_request), decisions (accepted/rejected/withdrawn)
and later removals as an append-only audit log. `release.parent_release_id` is
the source of truth for currently active membership; this table records how it
got that way.
"""
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import String, Text, ForeignKey, Boolean, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MembershipState(str, Enum):
    PENDING_REQUEST = "pending_request"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    REMOVED = "removed"


TERMINAL_STATES = {
    MembershipState.REJECTED.value,
    MembershipState.WITHDRAWN.value,
    MembershipState.REMOVED.value,
}


class ReleaseMembership(Base):
    __tablename__ = "release_membership"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    enterprise_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False, index=True
    )
    project_release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    late_scope: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_release_membership_enterprise_state", "enterprise_release_id", "state"),
        Index("ix_release_membership_project_state", "project_release_id", "state"),
    )
