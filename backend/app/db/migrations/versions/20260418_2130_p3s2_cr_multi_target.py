"""change_request → multi-env + multi-host targets (Phase 3 Step 2)

Creates the change_request_environment and change_request_host junction
tables, backfills the environment junction from the existing
change_request.environment_id column, then drops that column and relaxes
subsystem_id to nullable so platform / host-scoped CRs can be raised
without tying them to a specific subsystem.

Revision ID: p3s2crmt
Revises: p3s1infra
Create Date: 2026-04-18 21:30:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p3s2crmt"
down_revision: Union[str, None] = "p3s1infra"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    return table_name in Inspector.from_engine(conn).get_table_names()


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # ── change_request_environment ─────────────────────────────────────────
    if not _table_exists(conn, "change_request_environment"):
        op.create_table(
            "change_request_environment",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("change_request_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("change_request_id", "environment_id", name="uq_cr_environment"),
        )

    # Skip an `ix_..._id` index — the PrimaryKeyConstraint already covers
    # lookups on `id`, and naming one here would collide with the legacy
    # `ix_change_request_environment_id` that lives on change_request.environment_id
    # until we drop it further down.
    for idx_name, cols in [
        ("ix_change_request_environment_change_request_id", ["change_request_id"]),
        ("ix_change_request_environment_environment_id", ["environment_id"]),
        ("ix_change_request_environment_tenant_id", ["tenant_id"]),
    ]:
        if not _index_exists(conn, idx_name, "change_request_environment"):
            op.create_index(idx_name, "change_request_environment", cols)

    # ── change_request_host ────────────────────────────────────────────────
    if not _table_exists(conn, "change_request_host"):
        op.create_table(
            "change_request_host",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("change_request_id", sa.Integer(), nullable=False),
            sa.Column("infrastructure_component_id", sa.Integer(), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["infrastructure_component_id"], ["infrastructure_component.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("change_request_id", "infrastructure_component_id", name="uq_cr_host"),
        )

    for idx_name, cols in [
        ("ix_change_request_host_change_request_id", ["change_request_id"]),
        ("ix_change_request_host_infrastructure_component_id", ["infrastructure_component_id"]),
        ("ix_change_request_host_tenant_id", ["tenant_id"]),
    ]:
        if not _index_exists(conn, idx_name, "change_request_host"):
            op.create_index(idx_name, "change_request_host", cols)

    # ── Backfill ─────────────────────────────────────────────────────────────
    # Copy every legacy (change_request_id, environment_id, tenant_id) tuple
    # into the junction, skipping any that already exist (idempotent re-run).
    if _column_exists(conn, "change_request", "environment_id"):
        op.execute(
            sa.text(
                """
                INSERT INTO change_request_environment
                    (change_request_id, environment_id, tenant_id, created_at, updated_at)
                SELECT cr.id, cr.environment_id, cr.tenant_id, NOW(), NOW()
                FROM change_request cr
                WHERE cr.environment_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM change_request_environment j
                      WHERE j.change_request_id = cr.id
                        AND j.environment_id = cr.environment_id
                  )
                """
            )
        )

    # ── Drop legacy column + its index ──────────────────────────────────────
    if _index_exists(conn, "ix_change_request_environment_id", "change_request"):
        op.drop_index("ix_change_request_environment_id", table_name="change_request")
    if _column_exists(conn, "change_request", "environment_id"):
        op.drop_column("change_request", "environment_id")

    # ── Relax subsystem_id to nullable ──────────────────────────────────────
    if _column_exists(conn, "change_request", "subsystem_id"):
        with op.batch_alter_table("change_request") as batch:
            batch.alter_column("subsystem_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    conn = op.get_bind()

    # Re-add environment_id (nullable first so the ALTER succeeds on legacy rows)
    if not _column_exists(conn, "change_request", "environment_id"):
        op.add_column(
            "change_request",
            sa.Column("environment_id", sa.Integer(), nullable=True),
        )
        # Backfill with the first environment_id from the junction (arbitrary pick)
        op.execute(
            sa.text(
                """
                UPDATE change_request cr
                SET environment_id = sub.environment_id
                FROM (
                    SELECT DISTINCT ON (change_request_id) change_request_id, environment_id
                    FROM change_request_environment
                    ORDER BY change_request_id, id ASC
                ) sub
                WHERE cr.id = sub.change_request_id
                """
            )
        )
        with op.batch_alter_table("change_request") as batch:
            batch.alter_column("environment_id", existing_type=sa.Integer(), nullable=False)
        op.create_index("ix_change_request_environment_id", "change_request", ["environment_id"])
        op.create_foreign_key(
            "fk_change_request_environment_id",
            "change_request",
            "environment",
            ["environment_id"],
            ["id"],
        )

    # Re-require subsystem_id
    if _column_exists(conn, "change_request", "subsystem_id"):
        with op.batch_alter_table("change_request") as batch:
            batch.alter_column("subsystem_id", existing_type=sa.Integer(), nullable=False)

    if _table_exists(conn, "change_request_host"):
        op.drop_table("change_request_host")
    if _table_exists(conn, "change_request_environment"):
        op.drop_table("change_request_environment")
