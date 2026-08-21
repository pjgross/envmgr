"""Phase 9 C4 — rollback governance schema

Revision ID: rollbackgov
Revises: gatetypes
Create Date: 2026-08-21 08:23:23.198998

Additive: four new tables, no column changes to any existing table, and NO
BACKFILL. Existing tenants get their rollback policy lazily via
`rollback_policy_service.get_or_create_policy`, and existing releases
legitimately have no rollback plans — that absence is what a missing-plan
warning means. See app/db/models/rollback.py for what each table records and
why; nothing here refuses anything.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'rollbackgov'
down_revision: Union[str, None] = 'gatetypes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "release_rollback_plan",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("release.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=False),
        sa.Column("steps", sa.Text(), nullable=False),
        sa.Column("reversibility", sa.String(20), nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("agreed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("release_id", "system_id", name="uq_rollback_plan_release_system"),
    )
    op.create_index("ix_release_rollback_plan_tenant_id", "release_rollback_plan", ["tenant_id"])
    op.create_index("ix_release_rollback_plan_release_id", "release_rollback_plan", ["release_id"])
    op.create_index("ix_release_rollback_plan_system_id", "release_rollback_plan", ["system_id"])
    # Base declares `id` with index=True, so create_all builds this index on
    # every model-defined table — see the gatetypes migration for the same
    # comment. Without it here, a migration-built database differs from a
    # create_all-built one, and test_migration_schema_drift.py (column NAME
    # sets only) would not catch the difference.
    op.create_index("ix_release_rollback_plan_id", "release_rollback_plan", ["id"])

    op.create_table(
        "release_rollback_authorisation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("release.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("system_ids", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_release_rollback_authorisation_tenant_id", "release_rollback_authorisation", ["tenant_id"]
    )
    op.create_index(
        "ix_release_rollback_authorisation_release_id", "release_rollback_authorisation", ["release_id"]
    )
    op.create_index("ix_release_rollback_authorisation_id", "release_rollback_authorisation", ["id"])

    op.create_table(
        "rollback_rehearsal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("system_id", sa.Integer(), sa.ForeignKey("system.id"), nullable=False),
        sa.Column("rehearsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rehearsed_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_rollback_rehearsal_tenant_id", "rollback_rehearsal", ["tenant_id"])
    op.create_index("ix_rollback_rehearsal_system_id", "rollback_rehearsal", ["system_id"])
    op.create_index("ix_rollback_rehearsal_id", "rollback_rehearsal", ["id"])

    # NOTE: deliberately NO `deleted_at` column here — RollbackPolicy is
    # shaped like RaidConfig / EnvironmentNamingPolicy, one row per tenant
    # with no delete path, only updates. The task brief's own sample DDL for
    # this table included a `deleted_at` column that the model it was paired
    # with does not have; omitted here to match app/db/models/rollback.py and
    # its two precedents exactly.
    op.create_table(
        "rollback_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("require_rollback_plan", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "require_current_rehearsal", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("rehearsal_validity_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_rollback_policy_tenant_id", "rollback_policy", ["tenant_id"], unique=True
    )
    op.create_index("ix_rollback_policy_id", "rollback_policy", ["id"])


def downgrade() -> None:
    op.drop_index("ix_rollback_policy_id", table_name="rollback_policy")
    op.drop_index("ix_rollback_policy_tenant_id", table_name="rollback_policy")
    op.drop_table("rollback_policy")

    op.drop_index("ix_rollback_rehearsal_id", table_name="rollback_rehearsal")
    op.drop_index("ix_rollback_rehearsal_system_id", table_name="rollback_rehearsal")
    op.drop_index("ix_rollback_rehearsal_tenant_id", table_name="rollback_rehearsal")
    op.drop_table("rollback_rehearsal")

    op.drop_index("ix_release_rollback_authorisation_id", table_name="release_rollback_authorisation")
    op.drop_index(
        "ix_release_rollback_authorisation_release_id", table_name="release_rollback_authorisation"
    )
    op.drop_index(
        "ix_release_rollback_authorisation_tenant_id", table_name="release_rollback_authorisation"
    )
    op.drop_table("release_rollback_authorisation")

    op.drop_index("ix_release_rollback_plan_id", table_name="release_rollback_plan")
    op.drop_index("ix_release_rollback_plan_system_id", table_name="release_rollback_plan")
    op.drop_index("ix_release_rollback_plan_release_id", table_name="release_rollback_plan")
    op.drop_index("ix_release_rollback_plan_tenant_id", table_name="release_rollback_plan")
    op.drop_table("release_rollback_plan")
