"""Phase 9 C5a — cutover runbook.

A plan per (release, environment); tasks carried out by one team each, joined
by dependencies; an append-only history of every status change.

STATUS IS STORED, unlike the computed states elsewhere in this codebase: it is
a fact a person reports ("I started it"), not a function of other rows. What
is derived from it — schedule, lateness, criticality, the plan's state — is
computed on read by the runbook's schedule-computation service and never
stored.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TASK_STATUSES = ("not_started", "in_progress", "done", "failed", "skipped")
TASK_KINDS = ("task", "check", "deploy", "verification", "ramp")
DEPLOY_PATTERNS = ("rolling", "blue_green", "canary", "big_bang", "other")
# The ONE definition of "a successor may proceed past this task".
SATISFIED_STATUSES = frozenset({"done", "skipped"})


class RunbookPlan(Base):
    """At most one LIVE plan per (release, environment) — enforced in the
    runbook write service, not by a partial unique index (inert on SQLite)."""

    __tablename__ = "runbook_plan"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    environment_id: Mapped[int] = mapped_column(ForeignKey("environment.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    anchor_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deploy_pattern: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunbookTask(Base):
    __tablename__ = "runbook_task"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("runbook_plan.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    team_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("user_group.id"), nullable=True, index=True)
    # A system id, NOT a release_system id: release_system rows are
    # hard-deleted, which is how C4 came to have orphaned plans.
    system_id: Mapped[Optional[int]] = mapped_column(ForeignKey("system.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default="task")
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fixed_start_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="not_started")
    actual_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class RunbookTaskDependency(Base):
    """`task_id` cannot start until `predecessor_task_id` is done or skipped.
    Hard-deleted, like every junction row in this codebase."""

    __tablename__ = "runbook_task_dependency"
    __table_args__ = (
        UniqueConstraint("task_id", "predecessor_task_id", name="uq_runbook_task_dependency"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("runbook_task.id"), nullable=False, index=True)
    predecessor_task_id: Mapped[int] = mapped_column(
        ForeignKey("runbook_task.id"), nullable=False, index=True)


class RunbookTaskEvent(Base):
    """Append-only. `at` is when the change is SAID to have happened (a task is
    often ticked after it finished); `recorded_at` is server time."""

    __tablename__ = "runbook_task_event"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("runbook_task.id"), nullable=False, index=True)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    by_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    # Unused until C5b (pipeline updates); present now so C5b needs no migration.
    by_api_key_id: Mapped[Optional[int]] = mapped_column(ForeignKey("api_key.id"), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
