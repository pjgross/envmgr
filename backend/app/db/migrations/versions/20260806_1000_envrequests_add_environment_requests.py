"""environment requests + environment handover fields

Revision ID: envrequests
Revises: usergroups
Create Date: 2026-08-06 10:00:00.000000

Purely additive: one new table and six nullable columns. No backfill — an
environment with empty handover fields is a legitimate state, not a defect.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'envrequests'
down_revision: Union[str, None] = 'usergroups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=100), nullable=False),
        sa.Column("lifecycle_id", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("needed_by", sa.DateTime(timezone=True), nullable=True),
        sa.Column("environment_id", sa.Integer(), nullable=True),
        sa.Column("proposed_name", sa.String(length=200), nullable=True),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operations_group_id", sa.Integer(), nullable=True),
        sa.Column("created_environment_id", sa.Integer(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.ForeignKeyConstraint(["lifecycle_id"], ["lifecycle_template.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["user.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["tier_id"], ["environment_tier.id"]),
        sa.ForeignKeyConstraint(["operations_group_id"], ["user_group.id"]),
        sa.ForeignKeyConstraint(["created_environment_id"], ["environment.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Base declares id with index=True, so create_all emits ix_<table>_id.
    # The usergroups migration had to be corrected for omitting exactly this.
    op.create_index("ix_environment_request_id", "environment_request", ["id"])
    op.create_index("ix_environment_request_tenant_id", "environment_request", ["tenant_id"])
    op.create_index("ix_environment_request_lifecycle_id", "environment_request", ["lifecycle_id"])
    op.create_index("ix_environment_request_requested_by", "environment_request", ["requested_by"])
    op.create_index("ix_environment_request_environment_id", "environment_request", ["environment_id"])
    op.create_index(
        "ix_environment_request_operations_group_id", "environment_request",
        ["operations_group_id"],
    )
    op.create_index(
        "ix_environment_request_created_environment_id", "environment_request",
        ["created_environment_id"],
    )

    for column, type_ in (
        ("access_url", sa.String(length=500)),
        ("connection_notes", sa.Text()),
        ("support_contact", sa.String(length=255)),
        ("sla_notes", sa.Text()),
        ("known_limitations", sa.Text()),
        ("decommission_notes", sa.Text()),
    ):
        op.add_column("environment", sa.Column(column, type_, nullable=True))

    # Seed the default lifecycle for tenants that already exist. A literal copy
    # of DEFAULT_REQUEST_LIFECYCLE rather than an import: a migration
    # reproduces the past and must not change meaning when that module gains a
    # seventh state. mandatory=set() in ENTITY_FIELD_SPECS (booking_lifecycle.py)
    # is why field_permissions is {} here — a non-empty mandatory set would
    # require an editable_by entry per field in the initial state, which this
    # plain default deliberately doesn't carry; 'kind'/'justification' are
    # enforced by the service at submission time instead.
    conn = op.get_bind()
    tenant_ids = [row[0] for row in conn.execute(sa.text("SELECT id FROM tenant"))]
    definition = {
        "states": [
            {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
            {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
            {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            {"key": "fulfilled", "label": "Fulfilled", "is_initial": False, "is_terminal": True},
            {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
            {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from_state": "draft", "to_state": "submitted", "label": "Submit",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]},
            {"from_state": "draft", "to_state": "cancelled", "label": "Cancel",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]},
            {"from_state": "submitted", "to_state": "approved", "label": "Approve",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
            {"from_state": "approved", "to_state": "fulfilled", "label": "Mark Fulfilled",
             "allowed_roles": ["Admin", "Release Manager", "Test Manager"]},
        ],
        "field_permissions": {},
    }
    import json as _json
    for tenant_id in tenant_ids:
        conn.execute(
            sa.text(
                "INSERT INTO lifecycle_template "
                "(tenant_id, entity_type, name, description, is_default, is_system, definition) "
                "VALUES (:t, 'environment_request', 'Standard Request', "
                ":d, :is_default, :is_system, :def)"
            ),
            {
                "t": tenant_id,
                "d": "Raise, approve and fulfil environment requests.",
                "is_default": True,
                "is_system": False,
                "def": _json.dumps(definition),
            },
        )


def downgrade() -> None:
    # environment_request.lifecycle_id FKs to lifecycle_template with no
    # ondelete, so the table (and its rows, if any exist) must go before the
    # DELETE below — deleting the referenced templates first raises a
    # ForeignKeyViolationError the moment any request row exists.
    for index in (
        "ix_environment_request_created_environment_id",
        "ix_environment_request_operations_group_id",
        "ix_environment_request_environment_id",
        "ix_environment_request_requested_by",
        "ix_environment_request_lifecycle_id",
        "ix_environment_request_tenant_id",
        "ix_environment_request_id",
    ):
        op.drop_index(index, table_name="environment_request")
    op.drop_table("environment_request")

    # Scoped to this migration's own seeded row by name, not just
    # entity_type — a bare entity_type filter would also delete any template
    # a tenant authored themselves. Precedent:
    # 20260418_1930_p2s3_seed_cr_lifecycles.py's downgrade.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM lifecycle_template WHERE entity_type = 'environment_request' "
            "AND name = 'Standard Request'"
        )
    )

    for column in (
        "decommission_notes", "known_limitations", "sla_notes",
        "support_contact", "connection_notes", "access_url",
    ):
        op.drop_column("environment", column)
