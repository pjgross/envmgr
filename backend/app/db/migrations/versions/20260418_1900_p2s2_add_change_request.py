"""add change_request + change_history tables (Phase 2 Step 2)

Revision ID: p2s2change
Revises: p2s1lifecycle
Create Date: 2026-04-18 19:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p2s2change"
down_revision: Union[str, None] = "p2s1lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    return table_name in Inspector.from_engine(conn).get_table_names()


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # ── change_request ───────────────────────────────────────────────────────
    if not _table_exists(conn, "change_request"):
        op.create_table(
            "change_request",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(250), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("change_type", sa.String(50), nullable=False),
            sa.Column("status", sa.String(100), nullable=False, server_default="draft"),
            sa.Column("lifecycle_id", sa.Integer(), nullable=False),
            sa.Column("subsystem_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            # release_id: nullable int, no FK until Phase 3 creates the `release` table
            sa.Column("release_id", sa.Integer(), nullable=True),
            sa.Column("has_outage", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("outage_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("outage_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("raised_by", sa.Integer(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["lifecycle_id"], ["lifecycle_template.id"]),
            sa.ForeignKeyConstraint(["subsystem_id"], ["subsystem.id"]),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
            sa.ForeignKeyConstraint(["raised_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in [
        ("ix_change_request_id", ["id"]),
        ("ix_change_request_tenant_id", ["tenant_id"]),
        ("ix_change_request_lifecycle_id", ["lifecycle_id"]),
        ("ix_change_request_subsystem_id", ["subsystem_id"]),
        ("ix_change_request_environment_id", ["environment_id"]),
        ("ix_change_request_raised_by", ["raised_by"]),
    ]:
        if not _index_exists(conn, idx_name, "change_request"):
            op.create_index(idx_name, "change_request", cols)

    # ── change_history ───────────────────────────────────────────────────────
    if not _table_exists(conn, "change_history"):
        op.create_table(
            "change_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("change_request_id", sa.Integer(), nullable=False),
            sa.Column("from_state", sa.String(100), nullable=True),
            sa.Column("to_state", sa.String(100), nullable=True),
            sa.Column("field_name", sa.String(100), nullable=True),
            sa.Column("old_value", sa.JSON(), nullable=True),
            sa.Column("new_value", sa.JSON(), nullable=True),
            sa.Column("changed_by", sa.Integer(), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"]),
            sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in [
        ("ix_change_history_id", ["id"]),
        ("ix_change_history_change_request_id", ["change_request_id"]),
    ]:
        if not _index_exists(conn, idx_name, "change_history"):
            op.create_index(idx_name, "change_history", cols)


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "change_history"):
        op.drop_table("change_history")
    if _table_exists(conn, "change_request"):
        op.drop_table("change_request")
