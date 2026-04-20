"""phase 3 sub-project 4: gate criteria + drop release_gate.acceptance_criteria

Revision ID: p3s4gatecrit
Revises: p3s3releases
Create Date: 2026-04-20 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s4gatecrit"
down_revision: Union[str, None] = "p3s3releases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "gate_criterion"):
        op.create_table(
            "gate_criterion",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("gate_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(250), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("assigned_to_user_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_by_user_id", sa.Integer(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["gate_id"], ["release_gate.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["assigned_to_user_id"], ["user.id"]),
            sa.ForeignKeyConstraint(["completed_by_user_id"], ["user.id"]),
        )
        op.create_index("ix_gate_criterion_tenant_gate", "gate_criterion", ["tenant_id", "gate_id"])
        op.create_index(
            "ix_gate_criterion_assignee_status", "gate_criterion",
            ["tenant_id", "assigned_to_user_id", "status"],
        )

    if _column_exists(conn, "release_gate", "acceptance_criteria"):
        op.drop_column("release_gate", "acceptance_criteria")


def downgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "release_gate", "acceptance_criteria"):
        op.add_column("release_gate", sa.Column("acceptance_criteria", sa.Text(), nullable=True))

    if _table_exists(conn, "gate_criterion"):
        op.drop_index("ix_gate_criterion_assignee_status", table_name="gate_criterion")
        op.drop_index("ix_gate_criterion_tenant_gate", table_name="gate_criterion")
        op.drop_table("gate_criterion")
