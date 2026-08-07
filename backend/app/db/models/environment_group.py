"""Environment groups: a named set of environments, bookable as one unit.

Membership is a junction table because requirements.md §2.1 says an
environment may belong to MULTIPLE groups — a `group_id` column on
`environment` could not express that.

`EnvironmentGroup` is shaped like `Project` and `UserGroup`, the tenant-scoped
vocabularies this codebase already configures per tenant: soft-deleted, with
name uniqueness enforced in the service rather than by a partial unique index
— such an index is inert on SQLite and would guard only the PostgreSQL leg.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentGroup(Base):
    """A tenant-scoped, bookable set of environments."""

    __tablename__ = "environment_group"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Archived groups stay referenceable but stop being offered in pickers.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentGroup(id={self.id}, name='{self.name}', "
            f"tenant_id={self.tenant_id})>"
        )


class EnvironmentGroupMember(Base):
    """"Environment E is in group G."

    Soft-deleted rather than hard-deleted, unlike the dependency junctions in
    this codebase: membership has a history worth keeping, because a booking
    made against a group records only the group id, and answering "which
    environments did this group hold when that booking was made" later needs
    the removed rows to still exist.
    """

    __tablename__ = "environment_group_member"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("environment_group.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentGroupMember(group_id={self.group_id}, "
            f"environment_id={self.environment_id})>"
        )
