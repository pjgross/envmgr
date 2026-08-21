"""Phase 9 C4 — rollback governance.

Four tables that change together, so they live together: the per-component
plan, the authorisation raised when a rollback actually happens, the per-system
rehearsal, and the per-tenant policy that decides whether a missing plan is a
blocker or a warning in the readiness verdict.

NOTHING HERE REFUSES ANYTHING. C4 records; CI executes rollbacks.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Fixed, NOT tenant-configurable. Reversibility is a property of a database
# migration, not of a tenant's process — and the rollup in
# release_readiness_service orders these three, which a tenant-defined
# vocabulary could not support.
REVERSIBILITY_VALUES = ("reversible", "lossy", "irreversible")
REHEARSAL_OUTCOMES = ("passed", "failed", "partial")


class ReleaseRollbackPlan(Base):
    """How ONE component of a release would be rolled back.

    Per (release, system) rather than per release, because rollback is rarely
    uniform: a stateless API reverts by redeploying the previous artefact where
    a schema migration may be one-way.
    """

    __tablename__ = "release_rollback_plan"
    __table_args__ = (
        UniqueConstraint("release_id", "system_id", name="uq_rollback_plan_release_system"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    steps: Mapped[str] = mapped_column(Text, nullable=False)
    # reversible | lossy | irreversible. `lossy` is the value that earns its
    # place: teams say "reversible" when they mean "reversible if you accept
    # losing an hour of writes", and that is the distinction a sponsor needs.
    reversibility: Mapped[str] = mapped_column(String(20), nullable=False)
    estimated_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # BOTH NULLABLE, and the distinction is load-bearing: §2.11 asks for a plan
    # AGREED before deploy, so "written" and "agreed" are two states and an
    # unagreed draft is legitimate.
    agreed_by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    agreed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReleaseRollbackAuthorisation(Base):
    """The record of a rollback decision — raisable BEFORE OR AFTER the fact.

    Deliberately not attached to `Deployment`: a rollback may span several
    deployments, and the CI webhook that flips one to `rolled_back` knows the
    what but never the why.
    """

    __tablename__ = "release_rollback_authorisation"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(
        ForeignKey("release.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decided_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # A JSON list of system ids, not a junction table: the set is small and is
    # never queried from the system side. Same storage choice as
    # gate_type.expected_evidence and build.jira_tickets.
    system_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RollbackRehearsal(Base):
    """Evidence that rolling back a SYSTEM has actually been tried.

    Per system, not per release: one rehearsal serves every release touching
    that system until it goes stale. Rows accumulate as history; the latest is
    current — the shape gate_waiver uses. Freshness is COMPUTED on read.
    """

    __tablename__ = "rollback_rehearsal"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    system_id: Mapped[int] = mapped_column(ForeignKey("system.id"), nullable=False, index=True)
    rehearsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rehearsed_by_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RollbackPolicy(Base):
    """One row per tenant, shaped like RaidConfig.

    BOTH REQUIREMENTS DEFAULT OFF. Every release predating C4 has no plans, so
    blocking on day one would redden the whole estate and teach everyone to
    ignore the banner — the lesson C2's untyped gates and B5's idle detection
    both paid for.

    No `deleted_at`: same call as `RaidConfig` and `EnvironmentNamingPolicy` —
    there is no delete path for a tenant's policy, only updates.
    """

    __tablename__ = "rollback_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    require_rollback_plan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    require_current_rehearsal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rehearsal_validity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
