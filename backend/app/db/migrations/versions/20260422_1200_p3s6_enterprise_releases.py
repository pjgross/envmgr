"""phase 3 sub-project 6: enterprise releases (membership + lifecycle kind)

Revision ID: p3s6enterprise
Revises: p3s5scopelc
Create Date: 2026-04-22 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s6enterprise"
down_revision: Union[str, None] = "p3s5scopelc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return column in {c["name"] for c in Inspector.from_engine(conn).get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. release_membership ──
    if not _table_exists(conn, "release_membership"):
        op.create_table(
            "release_membership",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
            sa.Column("enterprise_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
            sa.Column("project_release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
            sa.Column("state", sa.String(30), nullable=False),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("removed_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
            sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("removal_reason", sa.Text(), nullable=True),
            sa.Column("late_scope", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )
        op.create_index(
            "ix_release_membership_tenant_id", "release_membership", ["tenant_id"]
        )
        op.create_index(
            "ix_release_membership_enterprise_state",
            "release_membership",
            ["enterprise_release_id", "state"],
        )
        op.create_index(
            "ix_release_membership_project_state",
            "release_membership",
            ["project_release_id", "state"],
        )
        # Partial unique indexes (PostgreSQL). SQLite ignores postgresql_where
        # and would create plain uniques, so we gate by dialect.
        if conn.dialect.name == "postgresql":
            op.create_index(
                "uq_membership_pending_per_project",
                "release_membership",
                ["project_release_id"],
                unique=True,
                postgresql_where=sa.text("state = 'pending_request'"),
            )
            op.create_index(
                "uq_membership_accepted_per_project",
                "release_membership",
                ["project_release_id"],
                unique=True,
                postgresql_where=sa.text("state = 'accepted'"),
            )

    # ── 2. lifecycle_template.applies_to_kind ──
    if not _column_exists(conn, "lifecycle_template", "applies_to_kind"):
        with op.batch_alter_table("lifecycle_template") as batch_op:
            batch_op.add_column(sa.Column("applies_to_kind", sa.String(20), nullable=True))

    # Backfill existing release lifecycle templates to applies_to_kind='project'.
    op.execute(
        "UPDATE lifecycle_template "
        "SET applies_to_kind = 'project' "
        "WHERE entity_type = 'release' AND applies_to_kind IS NULL"
    )


def downgrade() -> None:
    # Drop partial uniques first (safe if they don't exist).
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for idx in ("uq_membership_accepted_per_project", "uq_membership_pending_per_project"):
            try:
                op.drop_index(idx, table_name="release_membership")
            except Exception:
                pass

    if _table_exists(conn, "release_membership"):
        op.drop_index("ix_release_membership_project_state", table_name="release_membership")
        op.drop_index("ix_release_membership_enterprise_state", table_name="release_membership")
        op.drop_index("ix_release_membership_tenant_id", table_name="release_membership")
        op.drop_table("release_membership")

    if _column_exists(conn, "lifecycle_template", "applies_to_kind"):
        with op.batch_alter_table("lifecycle_template") as batch_op:
            batch_op.drop_column("applies_to_kind")
