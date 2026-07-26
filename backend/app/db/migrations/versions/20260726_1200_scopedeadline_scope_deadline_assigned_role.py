"""project release scope_deadline + gate_criterion assigned_role

Revision ID: scopedeadline
Revises: raidlogtables
Create Date: 2026-07-26 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "scopedeadline"
down_revision: Union[str, None] = "raidlogtables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "release", "scope_deadline"):
        op.add_column(
            "release",
            sa.Column("scope_deadline", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists(conn, "gate_criterion", "assigned_role"):
        op.add_column(
            "gate_criterion",
            sa.Column("assigned_role", sa.String(length=50), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "gate_criterion", "assigned_role"):
        op.drop_column("gate_criterion", "assigned_role")
    if _column_exists(conn, "release", "scope_deadline"):
        op.drop_column("release", "scope_deadline")
