"""Phase 7 B4 — soft/hard reservations and booking-type duration presets.

ADDITIVE ONLY: three columns, no backfill beyond the server defaults, no data
migration, no index. Every existing row lands on 'soft', which is what makes
this inert — see test_the_migration_is_inert in
tests/services/test_protection_verdict.py.

No index on protection_level: it is a low-cardinality filter always applied
alongside the tenant filter, so one would not be used. Phase 11 may want one
for an estate-wide cost aggregation; that is Phase 11's call, with a query in
front of it.

Revision ID: aabc21374208
Revises: envnamingpolicy
Create Date: 2026-08-10 21:13:26.767030

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aabc21374208'
down_revision: Union[str, None] = 'envnamingpolicy'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "booking_type",
        sa.Column(
            "default_protection_level",
            sa.String(20),
            nullable=False,
            server_default="soft",
        ),
    )
    op.add_column(
        "booking_type",
        sa.Column("default_duration_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "booking_request",
        sa.Column(
            "protection_level",
            sa.String(20),
            nullable=False,
            server_default="soft",
        ),
    )


def downgrade() -> None:
    op.drop_column("booking_request", "protection_level")
    op.drop_column("booking_type", "default_duration_minutes")
    op.drop_column("booking_type", "default_protection_level")
