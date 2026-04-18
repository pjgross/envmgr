"""add_event_log

Revision ID: cedd5a0a1194
Revises: 2436af1aef0c
Create Date: 2026-03-23 14:55:20.036494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'cedd5a0a1194'
down_revision: Union[str, None] = '2436af1aef0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
    )
    op.create_index("ix_event_log_id", "event_log", ["id"])
    op.create_index("ix_event_log_published_at", "event_log", ["published_at"])
    op.create_index("ix_event_log_tenant_id", "event_log", ["tenant_id"])
    op.create_index(
        "ix_event_log_published_at_created_at",
        "event_log",
        ["published_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_event_log_published_at_created_at", table_name="event_log")
    op.drop_index("ix_event_log_tenant_id", table_name="event_log")
    op.drop_index("ix_event_log_published_at", table_name="event_log")
    op.drop_index("ix_event_log_id", table_name="event_log")
    op.drop_table("event_log")
