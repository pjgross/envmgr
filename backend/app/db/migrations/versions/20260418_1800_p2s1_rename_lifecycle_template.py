"""rename booking_lifecycle_template to lifecycle_template + add entity_type

Part of Phase 2 Step 1: generalise lifecycle infrastructure so the same
table can hold lifecycle definitions for bookings, change requests, and
(later) releases.

Revision ID: p2s1lifecycle
Revises: 04df76ff6d6f
Create Date: 2026-04-18 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p2s1lifecycle"
down_revision: Union[str, None] = "04df76ff6d6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return table_name in inspector.get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(c["name"] == column_name for c in inspector.get_columns(table_name))


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    if not _table_exists(conn, table_name):
        return False
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    # Step 1: Rename legacy table to the generic name.
    #
    # Dev envs may be in split-brain if init_db/create_all ran after the model
    # rename but before this migration: both `booking_lifecycle_template` (with
    # any existing data + FK refs) and `lifecycle_template` (empty, from
    # create_all) will exist. In that case the create_all artifact is just a
    # schema echo of the model and carries no data; drop it and proceed with
    # the rename. Guard with a row-count check so we never destroy data by
    # accident in an edge case we haven't anticipated.
    if _table_exists(conn, "booking_lifecycle_template") and _table_exists(
        conn, "lifecycle_template"
    ):
        row_count = conn.execute(
            sa.text("SELECT COUNT(*) FROM lifecycle_template")
        ).scalar()
        if row_count and row_count > 0:
            raise RuntimeError(
                "Split-brain detected: both booking_lifecycle_template and "
                "lifecycle_template exist, and lifecycle_template has data. "
                "Manual reconciliation required before this migration can "
                "proceed."
            )
        op.drop_table("lifecycle_template")

    if _table_exists(conn, "booking_lifecycle_template") and not _table_exists(
        conn, "lifecycle_template"
    ):
        op.rename_table("booking_lifecycle_template", "lifecycle_template")
        # Rename PG auto-generated indexes to match the new table name.
        # (SQLite / tests use create_all, so this block is Postgres-only safe.)
        if conn.dialect.name == "postgresql":
            for old_name, new_name in [
                (
                    "ix_booking_lifecycle_template_id",
                    "ix_lifecycle_template_id",
                ),
                (
                    "ix_booking_lifecycle_template_tenant_id",
                    "ix_lifecycle_template_tenant_id",
                ),
            ]:
                if _index_exists(conn, old_name, "lifecycle_template"):
                    op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")

    # Step 2: Add `entity_type` column. Use server_default='booking' so existing
    # rows backfill cleanly; drop the default afterwards so new inserts must
    # provide the value explicitly.
    if _table_exists(conn, "lifecycle_template") and not _column_exists(
        conn, "lifecycle_template", "entity_type"
    ):
        op.add_column(
            "lifecycle_template",
            sa.Column(
                "entity_type",
                sa.String(50),
                nullable=False,
                server_default="booking",
            ),
        )
        # Remove the default so the column behaves identically to the ORM spec
        # going forward.
        op.alter_column("lifecycle_template", "entity_type", server_default=None)

    # Step 3: Composite index for tenant + entity_type lookups.
    if _table_exists(conn, "lifecycle_template") and not _index_exists(
        conn, "ix_lifecycle_template_tenant_entity", "lifecycle_template"
    ):
        op.create_index(
            "ix_lifecycle_template_tenant_entity",
            "lifecycle_template",
            ["tenant_id", "entity_type"],
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _index_exists(
        conn, "ix_lifecycle_template_tenant_entity", "lifecycle_template"
    ):
        op.drop_index(
            "ix_lifecycle_template_tenant_entity", table_name="lifecycle_template"
        )

    if _column_exists(conn, "lifecycle_template", "entity_type"):
        op.drop_column("lifecycle_template", "entity_type")

    if _table_exists(conn, "lifecycle_template") and not _table_exists(
        conn, "booking_lifecycle_template"
    ):
        op.rename_table("lifecycle_template", "booking_lifecycle_template")
        if conn.dialect.name == "postgresql":
            for old_name, new_name in [
                ("ix_lifecycle_template_id", "ix_booking_lifecycle_template_id"),
                (
                    "ix_lifecycle_template_tenant_id",
                    "ix_booking_lifecycle_template_tenant_id",
                ),
            ]:
                if _index_exists(
                    conn, old_name, "booking_lifecycle_template"
                ):
                    op.execute(f"ALTER INDEX {old_name} RENAME TO {new_name}")
