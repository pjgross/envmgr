"""RAID log tables: raid_item, raid_config, scope link, relation, history

Creates the five RAID-log tables. Enum-like columns are VARCHAR (no native
enums). Every table is tenant-scoped (tenant_id FK + index). raid_item carries
deleted_at for soft delete.

The (release_id, item_type, seq) reference-code natural key is enforced by a
partial unique index (uq_raid_item_ref) WHERE deleted_at IS NULL so soft-deleted
rows can reuse a seq. Postgres-only (nameuniqguard style): SQLite (test DB)
recreates schema via Base.metadata and is not migrated. The inline
UniqueConstraints on scope-link and relation are created unconditionally by
create_table and are fine on SQLite.

Revision ID: raidlogtables
Revises: scopeprojfields
Create Date: 2026-07-18 14:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "raidlogtables"
down_revision: Union[str, None] = "scopeprojfields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raid_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("release_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(20), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("raised_by", sa.Integer(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("probability", sa.SmallInteger(), nullable=True),
        sa.Column("impact", sa.SmallInteger(), nullable=True),
        sa.Column("response_strategy", sa.String(20), nullable=True),
        sa.Column("mitigation_plan", sa.Text(), nullable=True),
        sa.Column("contingency_plan", sa.Text(), nullable=True),
        sa.Column("validation_status", sa.String(20), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("resolution_plan", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False),
        sa.Column("direction", sa.String(20), nullable=True),
        sa.Column("counterparty", sa.String(200), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("at_risk", sa.Boolean(), nullable=False),
        sa.Column("release_dependency_id", sa.Integer(), nullable=True),
        sa.Column("promoted_from_id", sa.Integer(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"]),
        sa.ForeignKeyConstraint(["raised_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["release_dependency_id"], ["release_dependency.id"]),
        sa.ForeignKeyConstraint(["promoted_from_id"], ["raid_item.id"]),
    )
    op.create_index("ix_raid_item_tenant_id", "raid_item", ["tenant_id"])
    op.create_index("ix_raid_item_release_id", "raid_item", ["release_id"])

    op.create_table(
        "raid_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("probability_scale", sa.JSON(), nullable=False),
        sa.Column("impact_scale", sa.JSON(), nullable=False),
        sa.Column("rag_bands", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.UniqueConstraint("tenant_id", name="uq_raid_config_tenant"),
    )
    op.create_index("ix_raid_config_tenant_id", "raid_config", ["tenant_id"])

    op.create_table(
        "raid_item_scope_link",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("raid_item_id", sa.Integer(), nullable=False),
        sa.Column("release_change_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["raid_item_id"], ["raid_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["release_change_id"], ["release_change.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("raid_item_id", "release_change_id", name="uq_raid_scope_link"),
    )
    op.create_index("ix_raid_item_scope_link_tenant_id", "raid_item_scope_link", ["tenant_id"])
    op.create_index("ix_raid_item_scope_link_raid_item_id", "raid_item_scope_link", ["raid_item_id"])
    op.create_index("ix_raid_item_scope_link_release_change_id", "raid_item_scope_link", ["release_change_id"])

    op.create_table(
        "raid_item_relation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("from_item_id", sa.Integer(), nullable=False),
        sa.Column("to_item_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["from_item_id"], ["raid_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_item_id"], ["raid_item.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("from_item_id", "to_item_id", "relation", name="uq_raid_relation"),
        sa.CheckConstraint("from_item_id != to_item_id", name="ck_raid_relation_self"),
    )
    op.create_index("ix_raid_item_relation_tenant_id", "raid_item_relation", ["tenant_id"])
    op.create_index("ix_raid_item_relation_from_item_id", "raid_item_relation", ["from_item_id"])
    op.create_index("ix_raid_item_relation_to_item_id", "raid_item_relation", ["to_item_id"])

    op.create_table(
        "raid_item_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("raid_item_id", sa.Integer(), nullable=False),
        sa.Column("field_name", sa.String(50), nullable=False),
        sa.Column("old_value", sa.JSON(), nullable=True),
        sa.Column("new_value", sa.JSON(), nullable=True),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["raid_item_id"], ["raid_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
    )
    op.create_index("ix_raid_item_history_tenant_id", "raid_item_history", ["tenant_id"])
    op.create_index("ix_raid_item_history_raid_item_id", "raid_item_history", ["raid_item_id"])

    # Partial unique index for the (release_id, item_type, seq) ref-code natural
    # key. Partial (WHERE deleted_at IS NULL) so soft-deleted rows can reuse a
    # seq. Postgres-only: SQLite test DB recreates schema via Base.metadata.
    if op.get_bind().dialect.name == "postgresql":
        op.create_index(
            "uq_raid_item_ref", "raid_item", ["release_id", "item_type", "seq"],
            unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        try:
            op.drop_index("uq_raid_item_ref", table_name="raid_item")
        except Exception:
            pass

    op.drop_table("raid_item_history")
    op.drop_table("raid_item_relation")
    op.drop_table("raid_item_scope_link")
    op.drop_table("raid_config")
    op.drop_table("raid_item")
