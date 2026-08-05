"""Tenant-scoped groups of users.

Deliberately generic rather than an "operations team": Phase 7 A1 adds
`Project` + members, also a container of users, and two unrelated membership
models would leave users asking which one to add someone to. Anything that
needs a group adds its own FK, the way `environment.operations_group_id` does.

Membership grants no permissions. Every authorization rule in this app is
role-based, and B3a deliberately does not add a second axis — see the spec.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserGroup(Base):
    """A named group of users within one tenant.

    Soft-deleted, because `environment.operations_group_id` and (later) B3b's
    request history keep pointing at it after retirement. Name uniqueness is
    enforced in the service, not by a constraint here: a partial unique index
    (`WHERE deleted_at IS NULL`) is inert on SQLite, so it would guard only the
    PostgreSQL leg while the SQLite leg passed regardless. Same call, and the
    same reason, as EnvironmentTier.
    """

    __tablename__ = "user_group"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<UserGroup(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class UserGroupMember(Base):
    """A user's membership of a group.

    Hard-deleted, per this codebase's convention for junction rows: removing
    someone from a team is routine and should not accumulate tombstones.

    `tenant_id` is denormalised (it is derivable through `group_id`) so this
    table obeys the same "every tenant-scoped query filters on tenant_id" rule
    as every other table here, without a join.
    """

    __tablename__ = "user_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_user_group_member"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("user_group.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<UserGroupMember(group_id={self.group_id}, user_id={self.user_id})>"
