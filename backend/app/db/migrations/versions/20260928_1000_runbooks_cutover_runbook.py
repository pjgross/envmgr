"""runbooks — Phase 9 C5a cutover runbook

Revision ID: runbooks
Revises: closeout
Create Date: 2026-09-28 10:00:00

Additive: four tables, no change to any existing table, no backfill, no seed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "runbooks"
down_revision: Union[str, None] = "closeout"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "runbook_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
        sa.Column("environment_id", sa.Integer(), sa.ForeignKey("environment.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("anchor_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deploy_pattern", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "release_id", "environment_id"):
        op.create_index(f"ix_runbook_plan_{col}", "runbook_plan", [col])

    op.create_table(
        "runbook_task",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("plan_id", sa.Integer(), sa.ForeignKey("runbook_plan.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("team_group_id", sa.Integer(), sa.ForeignKey("user_group.id"), nullable=True),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="task"),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fixed_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("actual_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "plan_id", "team_group_id", "system_id"):
        op.create_index(f"ix_runbook_task_{col}", "runbook_task", [col])

    op.create_table(
        "runbook_task_dependency",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        sa.Column("predecessor_task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("task_id", "predecessor_task_id", name="uq_runbook_task_dependency"),
    )
    for col in ("id", "tenant_id", "task_id", "predecessor_task_id"):
        op.create_index(f"ix_runbook_task_dependency_{col}", "runbook_task_dependency", [col])

    op.create_table(
        "runbook_task_event",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("runbook_task.id"), nullable=False),
        sa.Column("from_status", sa.String(20), nullable=False),
        sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("by_api_key_id", sa.Integer(), sa.ForeignKey("api_key.id"), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        *_timestamps(),
    )
    for col in ("id", "tenant_id", "task_id"):
        op.create_index(f"ix_runbook_task_event_{col}", "runbook_task_event", [col])


def downgrade() -> None:
    op.drop_table("runbook_task_event")
    op.drop_table("runbook_task_dependency")
    op.drop_table("runbook_task")
    op.drop_table("runbook_plan")
