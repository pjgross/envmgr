"""Projects, their teams, and which environments they have agreed to use.

A project's members are NOT a table here. `team_group_id` points at B3a's
`UserGroup`, which was deliberately generic — not called `OperationsTeam` —
precisely so this sub-project could reuse it. One membership model, one admin
screen, and a person's group memberships answer both "which environments do you
operate" and "which projects are you on".

`UsageAgreement` records that a project may use an environment, optionally
within a window. **A1 records it and nothing reads it**: no booking is
rejected, nothing warns. Enforcement is A3, with its own rules — keeping a
behaviour change out of the sub-project that introduces the schema is the same
call B3a made with group membership.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    """A tenant-scoped project.

    Shaped like `UserGroup` and `EnvironmentTier`, the two vocabularies this
    codebase already configures per tenant: soft-deleted, with name uniqueness
    enforced in the service rather than by a partial unique index — such an
    index is inert on SQLite and would guard only the PostgreSQL leg.
    """

    __tablename__ = "project"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # A4's contention priority. LOWER WINS: rank 1 outranks rank 2.
    #
    # NULL MEANS UNRANKED, and that is a real state rather than a missing
    # value — no project has a rank on first deploy and there is no backfill.
    # A4's verdict reports an unranked pair as "priority does not separate
    # these", never as a loss: treating unranked as lowest would declare the
    # entire existing estate the loser the day this ships, which is the shape
    # B1's governance-gap chip took when it flagged every environment.
    priority_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True
    )
    # Archived projects stay referenceable but stop being offered in pickers.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class UsageAgreement(Base):
    """"Project P may use environment E, optionally between two dates."

    A junction rather than an owning FK on `environment`: shared estates are the
    normal case, and requirements.md §2.12 frames these as how projects
    "cooperate in a shared environment".

    Soft-deleted rather than hard-deleted despite being a junction: an agreement
    is a statement of intent with a history worth keeping, and A3 will want to
    know an agreement was withdrawn rather than find it silently absent.
    """

    __tablename__ = "usage_agreement"
    __table_args__ = (
        # A3's coverage EXISTS correlates on exactly this pair — see
        # agreement_gap_service.covered_exists_clause — and it runs on every
        # `GET /bookings` load, once for the page. `project_id` and
        # `environment_id` each had their own single-column index from A1, which
        # forces the planner to pick one and filter the rest; this is the pair it
        # actually asks for.
        #
        # Deliberately NOT prefixed with `tenant_id`, even though the clause
        # filters it: a `project_id` identifies exactly one project, which
        # belongs to exactly one tenant, so leading with `tenant_id` would only
        # put the low-cardinality column first. `deleted_at` is left out for the
        # same reason it is left out of every other index here — it is the
        # majority value, not a discriminator.
        Index("ix_usage_agreement_project_env", "project_id", "environment_id"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    starts_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ends_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<UsageAgreement(project_id={self.project_id}, "
            f"environment_id={self.environment_id})>"
        )
