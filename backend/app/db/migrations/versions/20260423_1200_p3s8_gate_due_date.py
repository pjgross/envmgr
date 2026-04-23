"""phase 3 sub-project 8: release_gate due_date replaces phase link

Revision ID: p3s8gateduedate
Revises: p3s7memuniq
Create Date: 2026-04-23 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s8gateduedate"
down_revision: Union[str, None] = "p3s7memuniq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def _index_exists(conn, table: str, name: str) -> bool:
    return any(i["name"] == name for i in Inspector.from_engine(conn).get_indexes(table))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add due_date nullable.
    if not _column_exists(conn, "release_gate", "due_date"):
        op.add_column(
            "release_gate",
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        )

    dialect = conn.dialect.name

    # 2a. Backfill from linked phase end_date.
    if _column_exists(conn, "release_gate", "test_phase_id"):
        op.execute("""
            UPDATE release_gate AS rg
               SET due_date = tp.end_date
              FROM test_phase AS tp
             WHERE rg.due_date IS NULL
               AND rg.test_phase_id = tp.id
               AND tp.end_date IS NOT NULL
        """ if dialect == "postgresql" else """
            UPDATE release_gate
               SET due_date = (
                   SELECT tp.end_date FROM test_phase tp
                    WHERE tp.id = release_gate.test_phase_id
                      AND tp.end_date IS NOT NULL
               )
             WHERE due_date IS NULL
               AND test_phase_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM test_phase tp
                    WHERE tp.id = release_gate.test_phase_id
                      AND tp.end_date IS NOT NULL
               )
        """)

    # 2b. Backfill from MAX(criterion.due_date).
    if _column_exists(conn, "gate_criterion", "due_date"):
        op.execute("""
            UPDATE release_gate AS rg
               SET due_date = (
                   SELECT MAX(gc.due_date) FROM gate_criterion gc
                    WHERE gc.gate_id = rg.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
             WHERE rg.due_date IS NULL
               AND EXISTS (
                   SELECT 1 FROM gate_criterion gc
                    WHERE gc.gate_id = rg.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
        """ if dialect == "postgresql" else """
            UPDATE release_gate
               SET due_date = (
                   SELECT MAX(gc.due_date) FROM gate_criterion gc
                    WHERE gc.gate_id = release_gate.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
             WHERE due_date IS NULL
               AND EXISTS (
                   SELECT 1 FROM gate_criterion gc
                    WHERE gc.gate_id = release_gate.id
                      AND gc.deleted_at IS NULL
                      AND gc.due_date IS NOT NULL
               )
        """)

    # 2c. Backfill from release.target_date.
    op.execute("""
        UPDATE release_gate
           SET due_date = (
               SELECT r.target_date FROM release r
                WHERE r.id = release_gate.release_id
                  AND r.target_date IS NOT NULL
           )
         WHERE due_date IS NULL
           AND EXISTS (
               SELECT 1 FROM release r
                WHERE r.id = release_gate.release_id
                  AND r.target_date IS NOT NULL
           )
    """)

    # 2d. Final fallback: release.created_at.
    op.execute("""
        UPDATE release_gate
           SET due_date = (
               SELECT r.created_at FROM release r
                WHERE r.id = release_gate.release_id
           )
         WHERE due_date IS NULL
    """)

    # 3. NOT NULL.
    op.alter_column("release_gate", "due_date", nullable=False)

    # 4. Drop the phase FK + index + column.
    if _index_exists(conn, "release_gate", "ix_release_gate_test_phase_id"):
        op.drop_index("ix_release_gate_test_phase_id", table_name="release_gate")
    if _column_exists(conn, "release_gate", "test_phase_id"):
        op.drop_column("release_gate", "test_phase_id")

    # 5. Drop gate_criterion.due_date.
    if _column_exists(conn, "gate_criterion", "due_date"):
        op.drop_column("gate_criterion", "due_date")


def downgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "gate_criterion", "due_date"):
        op.add_column(
            "gate_criterion",
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        )

    if not _column_exists(conn, "release_gate", "test_phase_id"):
        op.add_column(
            "release_gate",
            sa.Column("test_phase_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            None, "release_gate", "test_phase",
            ["test_phase_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index(
            "ix_release_gate_test_phase_id", "release_gate", ["test_phase_id"]
        )

    if _column_exists(conn, "release_gate", "due_date"):
        op.drop_column("release_gate", "due_date")
