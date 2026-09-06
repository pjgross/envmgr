"""gonogo go no go decision record

Revision ID: gonogo
Revises: pirbackfill
Create Date: 2026-09-05 22:45:13.677794

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'gonogo'
down_revision: Union[str, None] = 'pirbackfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "go_no_go_perspective",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", name="uq_go_no_go_perspective_tenant_name"
        ),
    )
    op.create_index("ix_go_no_go_perspective_tenant_id", "go_no_go_perspective", ["tenant_id"])
    # Base declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here, a migration-built database
    # differs from a create_all-built one — not caught by
    # test_migration_schema_drift.py, which compares only tables and columns.
    op.create_index("ix_go_no_go_perspective_id", "go_no_go_perspective", ["id"])

    op.create_table(
        "go_no_go_decision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column(
            "release_id", sa.Integer(),
            sa.ForeignKey("release.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("chaired_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("attendees", sa.JSON(), nullable=False),
        sa.Column("snapshot_ok", sa.Boolean(), nullable=False),
        sa.Column("snapshot_blockers", sa.JSON(), nullable=False),
        sa.Column("snapshot_warnings", sa.JSON(), nullable=False),
        sa.Column("snapshot_reversibility", sa.String(20), nullable=True),
        sa.Column("snapshot_rehearsal_state", sa.String(30), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_go_no_go_decision_tenant_id", "go_no_go_decision", ["tenant_id"])
    op.create_index("ix_go_no_go_decision_release_id", "go_no_go_decision", ["release_id"])
    op.create_index("ix_go_no_go_decision_id", "go_no_go_decision", ["id"])

    op.create_table(
        "go_no_go_signoff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id", sa.Integer(),
            sa.ForeignKey("go_no_go_decision.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "perspective_id", sa.Integer(),
            sa.ForeignKey("go_no_go_perspective.id"), nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("dissent_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "decision_id", "perspective_id", "user_id", name="uq_go_no_go_signoff_unique"
        ),
    )
    op.create_index("ix_go_no_go_signoff_decision_id", "go_no_go_signoff", ["decision_id"])
    op.create_index("ix_go_no_go_signoff_id", "go_no_go_signoff", ["id"])

    op.create_table(
        "go_no_go_condition",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "decision_id", sa.Integer(),
            sa.ForeignKey("go_no_go_decision.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("met_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("met_by_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_go_no_go_condition_decision_id", "go_no_go_condition", ["decision_id"])
    op.create_index("ix_go_no_go_condition_id", "go_no_go_condition", ["id"])

    # Backfill the three perspectives for every tenant that exists NOW. A
    # literal copy, not an import from go_no_go_defaults: a migration
    # reproduces the past and must not change meaning when that module gains
    # a fourth perspective. Tenants created after this runs are seeded by
    # tenant_service.create_tenant, so there is NO standing deploy step.
    conn = op.get_bind()
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenant"))]
    for tenant_id in tenant_ids:
        for name, description, sort_order in [
            ("Quality", "Test coverage, defects and quality evidence. Typically the Test Manager.", 10),
            ("Process", "Gates, change process and readiness. Typically the Release Manager.", 20),
            ("Acceptance", "Business acceptance of the change and its risk. Typically the sponsor.", 30),
        ]:
            conn.execute(
                sa.text(
                    "INSERT INTO go_no_go_perspective "
                    "(tenant_id, name, description, sort_order, is_active, created_at, updated_at) "
                    "VALUES (:t, :n, :d, :s, TRUE, NOW(), NOW())"
                ),
                {"t": tenant_id, "n": name, "d": description, "s": sort_order},
            )


def downgrade() -> None:
    op.drop_index("ix_go_no_go_condition_id", table_name="go_no_go_condition")
    op.drop_index("ix_go_no_go_condition_decision_id", table_name="go_no_go_condition")
    op.drop_table("go_no_go_condition")

    op.drop_index("ix_go_no_go_signoff_id", table_name="go_no_go_signoff")
    op.drop_index("ix_go_no_go_signoff_decision_id", table_name="go_no_go_signoff")
    op.drop_table("go_no_go_signoff")

    op.drop_index("ix_go_no_go_decision_id", table_name="go_no_go_decision")
    op.drop_index("ix_go_no_go_decision_release_id", table_name="go_no_go_decision")
    op.drop_index("ix_go_no_go_decision_tenant_id", table_name="go_no_go_decision")
    op.drop_table("go_no_go_decision")

    op.drop_index("ix_go_no_go_perspective_id", table_name="go_no_go_perspective")
    op.drop_index("ix_go_no_go_perspective_tenant_id", table_name="go_no_go_perspective")
    op.drop_table("go_no_go_perspective")


