"""add infrastructure_component + environment_subsystem_host (Phase 3 Step 1)

Introduces the deployment-target model pulled forward from Phase 6. Subsystems
in an environment can be attached to one or more hosts via the new junction,
supporting replicas and multi-region topologies.

Revision ID: p3s1infra
Revises: p2s3seedcr
Create Date: 2026-04-18 21:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s1infra"
down_revision: Union[str, None] = "p2s3seedcr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    return table_name in Inspector.from_engine(conn).get_table_names()


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # ── infrastructure_component ─────────────────────────────────────────────
    if not _table_exists(conn, "infrastructure_component"):
        op.create_table(
            "infrastructure_component",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("component_type", sa.String(50), nullable=False),
            sa.Column("provider", sa.String(50), nullable=True),
            sa.Column("region", sa.String(100), nullable=True),
            sa.Column("location", sa.String(200), nullable=True),
            sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
            sa.Column("external_id", sa.String(250), nullable=True),
            sa.Column("custom_fields", sa.JSON(), nullable=True),
            sa.Column("tags", sa.JSON(), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "name", name="uq_infra_component_tenant_name"),
        )

    for idx_name, cols in [
        ("ix_infrastructure_component_id", ["id"]),
        ("ix_infrastructure_component_tenant_id", ["tenant_id"]),
    ]:
        if not _index_exists(conn, idx_name, "infrastructure_component"):
            op.create_index(idx_name, "infrastructure_component", cols)

    # ── environment_subsystem_host ──────────────────────────────────────────
    if not _table_exists(conn, "environment_subsystem_host"):
        op.create_table(
            "environment_subsystem_host",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("environment_subsystem_id", sa.Integer(), nullable=False),
            sa.Column("infrastructure_component_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(50), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["environment_subsystem_id"], ["environment_subsystem.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["infrastructure_component_id"], ["infrastructure_component.id"]
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "environment_subsystem_id",
                "infrastructure_component_id",
                name="uq_env_subsystem_host",
            ),
        )

    for idx_name, cols in [
        ("ix_environment_subsystem_host_id", ["id"]),
        ("ix_environment_subsystem_host_environment_subsystem_id", ["environment_subsystem_id"]),
        ("ix_environment_subsystem_host_infrastructure_component_id", ["infrastructure_component_id"]),
        ("ix_environment_subsystem_host_tenant_id", ["tenant_id"]),
    ]:
        if not _index_exists(conn, idx_name, "environment_subsystem_host"):
            op.create_index(idx_name, "environment_subsystem_host", cols)


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "environment_subsystem_host"):
        op.drop_table("environment_subsystem_host")
    if _table_exists(conn, "infrastructure_component"):
        op.drop_table("infrastructure_component")
