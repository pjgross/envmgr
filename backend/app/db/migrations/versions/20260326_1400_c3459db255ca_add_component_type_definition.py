"""add_component_type_definition

Revision ID: c3459db255ca
Revises: dc594e50fd7d
Create Date: 2026-03-26 14:00:01.084670

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'c3459db255ca'
down_revision: Union[str, None] = 'dc594e50fd7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return table_name in inspector.get_table_names()


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create component_type_definition table
    if not _table_exists(conn, "component_type_definition"):
        op.create_table(
            "component_type_definition",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(50), nullable=True),
            sa.Column("icon", sa.String(50), nullable=True),
            sa.Column("field_definitions", sa.JSON(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists(conn, "ix_component_type_definition_id", "component_type_definition"):
        op.create_index("ix_component_type_definition_id", "component_type_definition", ["id"])
    if not _index_exists(conn, "ix_component_type_definition_tenant_id", "component_type_definition"):
        op.create_index("ix_component_type_definition_tenant_id", "component_type_definition", ["tenant_id"])

    # 2. Add component_type_definition_id column to subsystem
    if not _column_exists(conn, "subsystem", "component_type_definition_id"):
        op.add_column("subsystem", sa.Column("component_type_definition_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_subsystem_component_type_definition_id",
            "subsystem",
            "component_type_definition",
            ["component_type_definition_id"],
            ["id"],
        )
    if not _index_exists(conn, "ix_subsystem_component_type_definition_id", "subsystem"):
        op.create_index("ix_subsystem_component_type_definition_id", "subsystem", ["component_type_definition_id"])


def downgrade() -> None:
    op.drop_index("ix_subsystem_component_type_definition_id", table_name="subsystem")
    op.drop_constraint("fk_subsystem_component_type_definition_id", "subsystem", type_="foreignkey")
    op.drop_column("subsystem", "component_type_definition_id")
    op.drop_index("ix_component_type_definition_tenant_id", table_name="component_type_definition")
    op.drop_index("ix_component_type_definition_id", table_name="component_type_definition")
    op.drop_table("component_type_definition")
