"""phase 3 sub-project 7: collapse membership partial uniques into one combined guard

Revision ID: p3s7memuniq
Revises: p3s6enterprise
Create Date: 2026-04-22 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p3s7memuniq"
down_revision: Union[str, None] = "p3s6enterprise"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return  # SQLite test DB does not support partial uniques; schema recreated via Base.metadata each test

    # Drop the two narrow partial uniques if they exist
    for idx in ("uq_membership_pending_per_project", "uq_membership_accepted_per_project"):
        try:
            op.drop_index(idx, table_name="release_membership")
        except Exception:
            pass

    # Single combined partial unique guarding the "one active membership per project" invariant
    op.create_index(
        "uq_membership_open_per_project",
        "release_membership",
        ["project_release_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('pending_request', 'accepted')"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    try:
        op.drop_index("uq_membership_open_per_project", table_name="release_membership")
    except Exception:
        pass

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
