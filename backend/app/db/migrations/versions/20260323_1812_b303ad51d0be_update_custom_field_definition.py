"""update_custom_field_definition

Revision ID: b303ad51d0be
Revises: b76537c3d46a
Create Date: 2026-03-23 18:12:47.952583

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b303ad51d0be'
down_revision: Union[str, None] = 'b76537c3d46a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop and recreate — no production data exists yet in this table
    op.drop_table("custom_field_definition")
    op.create_table(
        "custom_field_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("field_key", sa.String(100), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("field_type", sa.String(20), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("lifecycle_states", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_custom_field_definition_tenant_id", "custom_field_definition", ["tenant_id"])
    # Partial unique index: field keys unique per (tenant, entity_type) only among active (non-deleted) definitions
    op.create_index(
        "uq_custom_field_def_active",
        "custom_field_definition",
        ["tenant_id", "entity_type", "field_key"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    # NOTE: Intentionally does not reconstruct the prior schema — this is a pre-production
    # migration with no data to preserve. If you need to roll back, run `alembic upgrade head`
    # to re-apply. Do NOT use in a partial-downgrade scenario without manual intervention.
    op.drop_table("custom_field_definition")
