"""scope items: add project_code + project_name to release_change

Revision ID: scopeprojfields
Revises: nameuniqguard
Create Date: 2026-07-18 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "scopeprojfields"
down_revision: Union[str, None] = "nameuniqguard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "release_change", "project_code"):
        op.add_column("release_change", sa.Column("project_code", sa.String(50), nullable=True))
        op.create_index("ix_release_change_project_code", "release_change", ["project_code"])
    if not _column_exists(conn, "release_change", "project_name"):
        op.add_column("release_change", sa.Column("project_name", sa.String(200), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "release_change", "project_name"):
        op.drop_column("release_change", "project_name")
    if _column_exists(conn, "release_change", "project_code"):
        try:
            op.drop_index("ix_release_change_project_code", table_name="release_change")
        except Exception:
            pass
        op.drop_column("release_change", "project_code")
