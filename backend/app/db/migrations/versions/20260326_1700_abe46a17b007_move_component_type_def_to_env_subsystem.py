"""move_component_type_def_to_env_subsystem

Revision ID: abe46a17b007
Revises: c3459db255ca
Create Date: 2026-03-26 17:00:56.536507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'abe46a17b007'
down_revision: Union[str, None] = 'c3459db255ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _constraint_exists(conn, table_name: str, constraint_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(
        fk["name"] == constraint_name
        for fk in inspector.get_foreign_keys(table_name)
    )


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add component_type_definition_id and custom_fields to environment_subsystem
    if not _column_exists(conn, "environment_subsystem", "component_type_definition_id"):
        op.add_column(
            "environment_subsystem",
            sa.Column("component_type_definition_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_env_subsystem_component_type_definition_id",
            "environment_subsystem",
            "component_type_definition",
            ["component_type_definition_id"],
            ["id"],
        )

    if not _index_exists(conn, "ix_env_subsystem_component_type_definition_id", "environment_subsystem"):
        op.create_index(
            "ix_env_subsystem_component_type_definition_id",
            "environment_subsystem",
            ["component_type_definition_id"],
        )

    if not _column_exists(conn, "environment_subsystem", "custom_fields"):
        op.add_column(
            "environment_subsystem",
            sa.Column("custom_fields", sa.JSON(), nullable=True),
        )

    # 2. Drop component_type_definition_id from subsystem
    if _index_exists(conn, "ix_subsystem_component_type_definition_id", "subsystem"):
        op.drop_index("ix_subsystem_component_type_definition_id", table_name="subsystem")

    if _constraint_exists(conn, "subsystem", "fk_subsystem_component_type_definition_id"):
        op.drop_constraint("fk_subsystem_component_type_definition_id", "subsystem", type_="foreignkey")

    if _column_exists(conn, "subsystem", "component_type_definition_id"):
        op.drop_column("subsystem", "component_type_definition_id")


def downgrade() -> None:
    conn = op.get_bind()

    # 1. Re-add component_type_definition_id to subsystem
    if not _column_exists(conn, "subsystem", "component_type_definition_id"):
        op.add_column(
            "subsystem",
            sa.Column("component_type_definition_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_subsystem_component_type_definition_id",
            "subsystem",
            "component_type_definition",
            ["component_type_definition_id"],
            ["id"],
        )

    if not _index_exists(conn, "ix_subsystem_component_type_definition_id", "subsystem"):
        op.create_index("ix_subsystem_component_type_definition_id", "subsystem", ["component_type_definition_id"])

    # 2. Drop columns from environment_subsystem
    if _index_exists(conn, "ix_env_subsystem_component_type_definition_id", "environment_subsystem"):
        op.drop_index("ix_env_subsystem_component_type_definition_id", table_name="environment_subsystem")

    if _constraint_exists(conn, "environment_subsystem", "fk_env_subsystem_component_type_definition_id"):
        op.drop_constraint("fk_env_subsystem_component_type_definition_id", "environment_subsystem", type_="foreignkey")

    if _column_exists(conn, "environment_subsystem", "custom_fields"):
        op.drop_column("environment_subsystem", "custom_fields")

    if _column_exists(conn, "environment_subsystem", "component_type_definition_id"):
        op.drop_column("environment_subsystem", "component_type_definition_id")
