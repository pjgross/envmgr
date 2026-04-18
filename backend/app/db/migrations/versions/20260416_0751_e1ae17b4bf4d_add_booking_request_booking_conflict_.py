"""add booking_request, booking_conflict_ack, booking.booking_request_id

Revision ID: e1ae17b4bf4d
Revises: abe46a17b007
Create Date: 2026-04-16 07:51:08.649097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1ae17b4bf4d'
down_revision: Union[str, None] = 'abe46a17b007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # booking_request
    op.create_table(
        "booking_request",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("project_name", sa.String(200), nullable=False),
        sa.Column("booking_type_id", sa.Integer, sa.ForeignKey("booking_type.id"), nullable=False, index=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("context_tag", sa.String(50), nullable=False, server_default="none"),
        sa.Column("exclusive_use_requested", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("custom_fields", sa.JSON, nullable=True),
        sa.Column("booked_by", sa.Integer, sa.ForeignKey("user.id"), nullable=False, index=True),
        sa.Column("delegate_user_ids", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # booking_conflict_ack
    op.create_table(
        "booking_conflict_ack",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tenant_id", sa.Integer, sa.ForeignKey("tenant.id"), nullable=False, index=True),
        sa.Column("booking_id", sa.Integer, sa.ForeignKey("booking.id"), nullable=False, index=True),
        sa.Column("other_booking_id", sa.Integer, sa.ForeignKey("booking.id"), nullable=False, index=True),
        sa.Column("willing_to_share", sa.Boolean, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("acknowledged_by", sa.Integer, sa.ForeignKey("user.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("booking_id", "other_booking_id", name="uq_conflict_ack_pair"),
    )

    # booking.booking_request_id (nullable for now)
    op.add_column(
        "booking",
        sa.Column(
            "booking_request_id",
            sa.Integer,
            sa.ForeignKey("booking_request.id"),
            nullable=True,
            index=True,
        ),
    )

    # Backfill: one booking_request per existing booking. Each gets its own parent.
    op.execute(
        """
        INSERT INTO booking_request (
            tenant_id, project_name, booking_type_id, start_date, end_date,
            notes, context_tag, exclusive_use_requested, custom_fields,
            booked_by, delegate_user_ids, created_at, updated_at, deleted_at
        )
        SELECT
            tenant_id, project_name, booking_type_id, start_date, end_date,
            notes, context_tag, exclusive_use, custom_fields,
            booked_by, NULL, created_at, updated_at, deleted_at
        FROM booking
        WHERE booking_request_id IS NULL
        """
    )
    # Match each booking to the request we just inserted for it.
    # Note: this works because the backfill INSERT preserves ordering and
    # each source row gets exactly one new request row. For Postgres we
    # correlate on (tenant_id, project_name, booked_by, start_date, end_date, booking_type_id).
    op.execute(
        """
        UPDATE booking
        SET booking_request_id = (
            SELECT br.id FROM booking_request br
            WHERE br.tenant_id = booking.tenant_id
              AND br.project_name = booking.project_name
              AND br.booked_by = booking.booked_by
              AND br.booking_type_id = booking.booking_type_id
              AND br.start_date = booking.start_date
              AND br.end_date = booking.end_date
            ORDER BY br.id
            LIMIT 1
        )
        WHERE booking_request_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("booking", "booking_request_id")
    op.drop_table("booking_conflict_ack")
    op.drop_table("booking_request")
