"""add_system_component_dependencies

Revision ID: 408f62e493b5
Revises: 4b4d469a6e85
Create Date: 2026-03-23 13:57:04.886469

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '408f62e493b5'
down_revision: Union[str, None] = '4b4d469a6e85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_dependency",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_system_id", sa.Integer(), nullable=False),
        sa.Column("to_system_id", sa.Integer(), nullable=False),
        sa.Column(
            "dependency_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["from_system_id"], ["system.id"]),
        sa.ForeignKeyConstraint(["to_system_id"], ["system.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("from_system_id", "to_system_id", "tenant_id", name="uq_system_dep"),
    )
    op.create_index(
        op.f("ix_system_dependency_from_system_id"),
        "system_dependency",
        ["from_system_id"],
    )
    op.create_index(
        op.f("ix_system_dependency_to_system_id"),
        "system_dependency",
        ["to_system_id"],
    )
    op.create_index(
        op.f("ix_system_dependency_tenant_id"),
        "system_dependency",
        ["tenant_id"],
    )

    op.create_table(
        "component_dependency",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_subsystem_id", sa.Integer(), nullable=False),
        sa.Column("to_subsystem_id", sa.Integer(), nullable=False),
        sa.Column(
            "dependency_type",
            sa.String(),
            nullable=False,
        ),
        sa.Column("protocol", sa.String(50), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["from_subsystem_id"], ["subsystem.id"]),
        sa.ForeignKeyConstraint(["to_subsystem_id"], ["subsystem.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "from_subsystem_id", "to_subsystem_id", "tenant_id", name="uq_component_dep"
        ),
    )
    op.create_index(
        op.f("ix_component_dependency_from_subsystem_id"),
        "component_dependency",
        ["from_subsystem_id"],
    )
    op.create_index(
        op.f("ix_component_dependency_to_subsystem_id"),
        "component_dependency",
        ["to_subsystem_id"],
    )
    op.create_index(
        op.f("ix_component_dependency_tenant_id"),
        "component_dependency",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_component_dependency_tenant_id"), table_name="component_dependency"
    )
    op.drop_index(
        op.f("ix_component_dependency_to_subsystem_id"), table_name="component_dependency"
    )
    op.drop_index(
        op.f("ix_component_dependency_from_subsystem_id"), table_name="component_dependency"
    )
    op.drop_table("component_dependency")

    op.drop_index(
        op.f("ix_system_dependency_tenant_id"), table_name="system_dependency"
    )
    op.drop_index(
        op.f("ix_system_dependency_to_system_id"), table_name="system_dependency"
    )
    op.drop_index(
        op.f("ix_system_dependency_from_system_id"), table_name="system_dependency"
    )
    op.drop_table("system_dependency")
