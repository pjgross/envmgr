"""add_booking_lifecycle

Revision ID: dc594e50fd7d
Revises: 1a73d94d5fab
Create Date: 2026-03-25 11:19:17.622444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'dc594e50fd7d'
down_revision: Union[str, None] = '1a73d94d5fab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return table_name in inspector.get_table_names()


def _index_exists(conn, index_name: str, table_name: str) -> bool:
    inspector = Inspector.from_engine(conn)
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))



def upgrade() -> None:
    conn = op.get_bind()

    # 1. Create booking_lifecycle_template table (may already exist if init_db ran first)
    if not _table_exists(conn, "booking_lifecycle_template"):
        op.create_table(
            "booking_lifecycle_template",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("definition", postgresql.JSONB(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists(conn, "ix_booking_lifecycle_template_id", "booking_lifecycle_template"):
        op.create_index("ix_booking_lifecycle_template_id", "booking_lifecycle_template", ["id"])
    if not _index_exists(conn, "ix_booking_lifecycle_template_tenant_id", "booking_lifecycle_template"):
        op.create_index("ix_booking_lifecycle_template_tenant_id", "booking_lifecycle_template", ["tenant_id"])

    # 2. Create booking_type table
    if not _table_exists(conn, "booking_type"):
        op.create_table(
            "booking_type",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("lifecycle_template_id", sa.Integer(), nullable=False),
            sa.Column("color", sa.String(7), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["lifecycle_template_id"], ["booking_lifecycle_template.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists(conn, "ix_booking_type_id", "booking_type"):
        op.create_index("ix_booking_type_id", "booking_type", ["id"])
    if not _index_exists(conn, "ix_booking_type_tenant_id", "booking_type"):
        op.create_index("ix_booking_type_tenant_id", "booking_type", ["tenant_id"])
    if not _index_exists(conn, "ix_booking_type_lifecycle_template_id", "booking_type"):
        op.create_index("ix_booking_type_lifecycle_template_id", "booking_type", ["lifecycle_template_id"])

    # 3. Create booking_status_history table
    if not _table_exists(conn, "booking_status_history"):
        op.create_table(
            "booking_status_history",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("booking_id", sa.Integer(), nullable=False),
            sa.Column("from_state", sa.String(100), nullable=True),
            sa.Column("to_state", sa.String(100), nullable=False),
            sa.Column("changed_by", sa.Integer(), nullable=False),
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["booking_id"], ["booking.id"]),
            sa.ForeignKeyConstraint(["changed_by"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists(conn, "ix_booking_status_history_id", "booking_status_history"):
        op.create_index("ix_booking_status_history_id", "booking_status_history", ["id"])
    if not _index_exists(conn, "ix_booking_status_history_booking_id", "booking_status_history"):
        op.create_index("ix_booking_status_history_booking_id", "booking_status_history", ["booking_id"])

    # 4. Add new columns to booking (nullable first for backfill; IF NOT EXISTS handles re-runs)
    op.execute("""
        ALTER TABLE booking
            ADD COLUMN IF NOT EXISTS exclusive_use BOOLEAN,
            ADD COLUMN IF NOT EXISTS booking_type_id INTEGER,
            ADD COLUMN IF NOT EXISTS status_new VARCHAR(100)
    """)

    if not _index_exists(conn, "ix_booking_booking_type_id", "booking"):
        op.create_index("ix_booking_booking_type_id", "booking", ["booking_type_id"])

    # 5. Seed default lifecycle template per tenant
    op.execute("""
        INSERT INTO booking_lifecycle_template (tenant_id, name, is_default, definition, created_at, updated_at)
        SELECT
            t.id,
            'Default Lifecycle',
            true,
            '{
                "states": [
                    {"key": "draft", "label": "Draft", "is_initial": true, "is_terminal": false},
                    {"key": "submitted", "label": "Submitted", "is_initial": false, "is_terminal": false},
                    {"key": "approved", "label": "Approved", "is_initial": false, "is_terminal": false},
                    {"key": "rejected", "label": "Rejected", "is_initial": false, "is_terminal": true},
                    {"key": "extension_requested", "label": "Extension Request", "is_initial": false, "is_terminal": false},
                    {"key": "closed", "label": "Closed", "is_initial": false, "is_terminal": true}
                ],
                "transitions": [
                    {"from_state": "draft", "to_state": "submitted", "label": "Submit", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
                    {"from_state": "submitted", "to_state": "approved", "label": "Approve", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "submitted", "to_state": "rejected", "label": "Reject", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "approved", "to_state": "extension_requested", "label": "Request Extension", "allowed_roles": ["Admin", "ReleaseManager", "User"]},
                    {"from_state": "extension_requested", "to_state": "approved", "label": "Approve Extension", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "extension_requested", "to_state": "rejected", "label": "Reject Extension", "allowed_roles": ["Admin", "ReleaseManager"]},
                    {"from_state": "approved", "to_state": "closed", "label": "Close", "allowed_roles": ["Admin", "ReleaseManager"]}
                ],
                "field_permissions": {
                    "draft": {"editable_fields": ["project_name", "start_date", "end_date", "notes", "exclusive_use", "custom_fields"], "editable_by": ["Admin", "ReleaseManager", "User"]},
                    "submitted": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
                    "approved": {"editable_fields": ["notes"], "editable_by": ["Admin", "ReleaseManager"]},
                    "rejected": {"editable_fields": [], "editable_by": []},
                    "extension_requested": {"editable_fields": ["notes", "end_date"], "editable_by": ["Admin", "ReleaseManager"]},
                    "closed": {"editable_fields": [], "editable_by": []}
                }
            }'::jsonb,
            now(),
            now()
        FROM tenant t
        WHERE t.id NOT IN (SELECT tenant_id FROM booking_lifecycle_template)
    """)

    # 6. Seed default booking type per tenant
    op.execute("""
        INSERT INTO booking_type (tenant_id, name, lifecycle_template_id, is_active, created_at, updated_at)
        SELECT
            blt.tenant_id,
            'Standard Booking',
            blt.id,
            true,
            now(),
            now()
        FROM booking_lifecycle_template blt
        WHERE blt.is_default = true
          AND blt.tenant_id NOT IN (SELECT tenant_id FROM booking_type)
    """)

    # 7. Backfill booking.exclusive_use (exclusive -> true, shared -> false)
    # Values stored as lowercase strings because native_enum=False stores the enum .value
    op.execute("""
        UPDATE booking
        SET exclusive_use = CASE WHEN booking_type = 'exclusive' THEN true ELSE false END
        WHERE exclusive_use IS NULL
    """)

    # 8. Backfill booking.booking_type_id with default type for each tenant
    op.execute("""
        UPDATE booking b
        SET booking_type_id = bt.id
        FROM booking_type bt
        WHERE bt.tenant_id = b.tenant_id
          AND bt.name = 'Standard Booking'
          AND b.booking_type_id IS NULL
    """)

    # 9. Backfill booking.status_new mapping old status values
    op.execute("""
        UPDATE booking
        SET status_new = CASE
            WHEN status = 'pending'  THEN 'submitted'
            WHEN status = 'approved' THEN 'approved'
            WHEN status = 'rejected' THEN 'rejected'
            ELSE status
        END
        WHERE status_new IS NULL
    """)

    # 10. Seed booking_status_history (one row per existing booking)
    op.execute("""
        INSERT INTO booking_status_history (booking_id, from_state, to_state, changed_by, changed_at, created_at, updated_at)
        SELECT
            b.id,
            NULL,
            b.status_new,
            b.booked_by,
            b.created_at,
            now(),
            now()
        FROM booking b
        WHERE b.deleted_at IS NULL
          AND b.id NOT IN (SELECT booking_id FROM booking_status_history)
    """)

    # 11. Make new columns NOT NULL and drop old columns
    op.alter_column("booking", "exclusive_use", nullable=False, server_default=sa.text("false"))
    op.alter_column("booking", "booking_type_id", nullable=False)

    # Rename status_new -> status: drop old status column, rename new one
    op.drop_column("booking", "status")
    op.alter_column("booking", "status_new", new_column_name="status")
    op.alter_column("booking", "status", nullable=False)

    # Drop booking_type column (replaced by exclusive_use + booking_type_id)
    # Use IF EXISTS to avoid aborting the transaction if the index doesn't exist
    op.execute("DROP INDEX IF EXISTS ix_booking_booking_type")
    op.drop_column("booking", "booking_type")

    # Add FK constraint for booking_type_id
    op.create_foreign_key(
        "fk_booking_booking_type_id", "booking", "booking_type",
        ["booking_type_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_booking_booking_type_id", "booking", type_="foreignkey")
    op.add_column("booking", sa.Column("booking_type", sa.String(), nullable=True))
    op.execute("UPDATE booking SET booking_type = CASE WHEN exclusive_use THEN 'exclusive' ELSE 'shared' END")
    op.alter_column("booking", "booking_type", nullable=False)

    op.add_column("booking", sa.Column("status_old", sa.String(), nullable=True))
    op.execute("""
        UPDATE booking SET status_old = CASE
            WHEN status = 'submitted' THEN 'pending'
            WHEN status = 'approved' THEN 'approved'
            WHEN status = 'rejected' THEN 'rejected'
            ELSE 'pending'
        END
    """)
    op.drop_column("booking", "status")
    op.alter_column("booking", "status_old", new_column_name="status")
    op.alter_column("booking", "status", nullable=False, server_default=sa.text("'pending'"))

    op.drop_index("ix_booking_booking_type_id", table_name="booking")
    op.drop_column("booking", "booking_type_id")
    op.drop_column("booking", "exclusive_use")

    op.drop_index("ix_booking_status_history_booking_id", table_name="booking_status_history")
    op.drop_index("ix_booking_status_history_id", table_name="booking_status_history")
    op.drop_table("booking_status_history")
    op.drop_index("ix_booking_type_lifecycle_template_id", table_name="booking_type")
    op.drop_index("ix_booking_type_tenant_id", table_name="booking_type")
    op.drop_index("ix_booking_type_id", table_name="booking_type")
    op.drop_table("booking_type")
    op.drop_index("ix_booking_lifecycle_template_tenant_id", table_name="booking_lifecycle_template")
    op.drop_index("ix_booking_lifecycle_template_id", table_name="booking_lifecycle_template")
    op.drop_table("booking_lifecycle_template")
