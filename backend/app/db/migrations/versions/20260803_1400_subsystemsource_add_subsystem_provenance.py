"""subsystem provenance — source and source_path

Revision ID: subsystemsource
Revises: tenantsecrets
Create Date: 2026-08-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'subsystemsource'
down_revision: Union[str, None] = 'tenantsecrets'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows backfill to 'manual', including any a past scan created.
    # That errs quiet rather than noisy: those rows will not be reported as
    # drift until a scan re-stamps them, which apply() does on update as well
    # as on insert.
    op.add_column(
        "subsystem",
        sa.Column("source", sa.String(length=20), nullable=False,
                  server_default="manual"),
    )
    op.add_column(
        "subsystem",
        sa.Column("source_path", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subsystem", "source_path")
    op.drop_column("subsystem", "source")
