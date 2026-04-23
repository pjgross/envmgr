"""phase 3 sub-project 5: scope-item lifecycle (moves + histories + kind rules)

Revision ID: p3s5scopelc
Revises: p3s4gatecrit
Create Date: 2026-04-21 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s5scopelc"
down_revision: Union[str, None] = "p3s4gatecrit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_is_nullable(conn, table: str, column: str) -> bool:
    for c in Inspector.from_engine(conn).get_columns(table):
        if c["name"] == column:
            return bool(c.get("nullable"))
    return False


def upgrade() -> None:
    conn = op.get_bind()

    # ── 1. ALTER release_change.release_id to nullable + ON DELETE SET NULL ──
    # batch_alter_table so SQLite (used by tests) can rewrite the table.
    if not _column_is_nullable(conn, "release_change", "release_id"):
        with op.batch_alter_table("release_change") as batch_op:
            batch_op.alter_column(
                "release_id",
                existing_type=sa.Integer(),
                nullable=True,
            )
            # Drop the old CASCADE FK and add a SET NULL one. Constraint names
            # vary by backend, so use drop_constraint with the naming
            # convention fallback. On SQLite the batch op recreates the whole
            # table so this is safe.
            try:
                batch_op.drop_constraint("release_change_release_id_fkey", type_="foreignkey")
            except Exception:
                # Constraint name may differ on SQLite / auto-named
                pass
            batch_op.create_foreign_key(
                "fk_release_change_release_id_set_null",
                "release",
                ["release_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # ── 2. release_change_release_history ──
    if not _table_exists(conn, "release_change_release_history"):
        op.create_table(
            "release_change_release_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("change_id", sa.Integer(), nullable=False),
            sa.Column("from_release_id", sa.Integer(), nullable=True),
            sa.Column("to_release_id", sa.Integer(), nullable=True),
            sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("moved_by", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["change_id"], ["release_change.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["from_release_id"], ["release.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["to_release_id"], ["release.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["moved_by"], ["user.id"]),
        )
        op.create_index(
            "ix_rc_release_hist_tenant_change",
            "release_change_release_history",
            ["tenant_id", "change_id"],
        )

    # ── 3. release_change_status_history ──
    if not _table_exists(conn, "release_change_status_history"):
        op.create_table(
            "release_change_status_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("change_id", sa.Integer(), nullable=False),
            sa.Column("from_status", sa.String(100), nullable=True),
            sa.Column("to_status", sa.String(100), nullable=True),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("changed_by", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["change_id"], ["release_change.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
        )
        op.create_index(
            "ix_rc_status_hist_tenant_change",
            "release_change_status_history",
            ["tenant_id", "change_id"],
        )

    # ── 4. scope_change_kind_rule ──
    if not _table_exists(conn, "scope_change_kind_rule"):
        op.create_table(
            "scope_change_kind_rule",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("change_kind", sa.String(20), nullable=False),
            sa.Column("counts_as_scope_change", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        )
        op.create_index(
            "ix_scope_change_kind_rule_tenant_kind",
            "scope_change_kind_rule",
            ["tenant_id", "change_kind"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "scope_change_kind_rule"):
        op.drop_index("ix_scope_change_kind_rule_tenant_kind", table_name="scope_change_kind_rule")
        op.drop_table("scope_change_kind_rule")

    if _table_exists(conn, "release_change_status_history"):
        op.drop_index("ix_rc_status_hist_tenant_change", table_name="release_change_status_history")
        op.drop_table("release_change_status_history")

    if _table_exists(conn, "release_change_release_history"):
        op.drop_index("ix_rc_release_hist_tenant_change", table_name="release_change_release_history")
        op.drop_table("release_change_release_history")

    if _column_is_nullable(conn, "release_change", "release_id"):
        with op.batch_alter_table("release_change") as batch_op:
            batch_op.alter_column(
                "release_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            try:
                batch_op.drop_constraint("fk_release_change_release_id_set_null", type_="foreignkey")
            except Exception:
                pass
            batch_op.create_foreign_key(
                "release_change_release_id_fkey",
                "release",
                ["release_id"],
                ["id"],
                ondelete="CASCADE",
            )
