"""acknowledgement of a booking's usage-agreement gap

Revision ID: agreementack
Revises: envgroups
Create Date: 2026-08-08 12:00:00.000000

Additive. ONE new table and nothing else — `usage_agreement` itself is
deliberately untouched, because the gap is computed from it and never stored,
so nothing about it needs a new column.

No backfill: an absent row means "not acknowledged", which is the correct
answer for every booking that exists today.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'agreementack'
down_revision: Union[str, None] = 'envgroups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_agreement_ack",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        # NOT NULL, unlike booking_conflict_ack's pair: the row's existence IS
        # the acknowledgement, so it cannot meaningfully lack an author or a
        # timestamp. Matches the model, which types both non-Optional.
        sa.Column("acknowledged_by", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["booking_id"], ["booking.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
        # One booking, one answer. Named to match the model's __table_args__.
        sa.UniqueConstraint("booking_id", name="uq_agreement_ack_booking"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_usage_agreement_ack_id", "usage_agreement_ack", ["id"])
    op.create_index(
        "ix_usage_agreement_ack_tenant_id", "usage_agreement_ack", ["tenant_id"]
    )
    op.create_index(
        "ix_usage_agreement_ack_booking_id", "usage_agreement_ack", ["booking_id"]
    )


def downgrade() -> None:
    for index in (
        "ix_usage_agreement_ack_booking_id",
        "ix_usage_agreement_ack_tenant_id",
        "ix_usage_agreement_ack_id",
    ):
        op.drop_index(index, table_name="usage_agreement_ack")
    op.drop_table("usage_agreement_ack")
