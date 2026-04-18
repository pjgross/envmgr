"""seed default change-request lifecycle templates for existing tenants

Phase 2 Step 3 — complements the runtime seeding that new tenants get via
tenant_service.create_tenant, so tenants provisioned before Phase 2 land
can also raise change requests out of the box.

Revision ID: p2s3seedcr
Revises: p2s2change
Create Date: 2026-04-18 19:30:00
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p2s3seedcr"
down_revision: Union[str, None] = "p2s2change"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with DEFAULT_LIFECYCLE_DEFINITIONS in
# backend/app/services/change_request_service.py. If you change one, mirror
# the other — tenant_service.create_tenant uses the service constant for new
# tenants; this migration uses the JSON below for existing tenants.
_SIMPLE_APPROVAL = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "submitted", "label": "Submit",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve",
         "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
         "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
         "allowed_roles": ["Admin", "Release Manager"]},
        {"from_state": "approved", "to_state": "completed", "label": "Mark Completed",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
    ],
    "field_permissions": {},
}

_EMERGENCY = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "in_progress", "label": "In Progress", "is_initial": False, "is_terminal": False},
        {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft", "to_state": "in_progress", "label": "Start",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
        {"from_state": "in_progress", "to_state": "completed", "label": "Mark Completed",
         "allowed_roles": ["Admin", "Release Manager", "Test Manager", "Developer"]},
    ],
    "field_permissions": {},
}


def upgrade() -> None:
    conn = op.get_bind()
    # Guard in case the generic lifecycle_template table hasn't been created yet
    # (e.g. running migrations out of order on a fresh DB).
    if "lifecycle_template" not in Inspector.from_engine(conn).get_table_names():
        return

    for name, definition, is_default, description in [
        ("Simple Approval", _SIMPLE_APPROVAL, True,
         "Standard change-request flow with an approval gate."),
        ("Emergency", _EMERGENCY, False,
         "Minimal flow for urgent changes — no approval gate."),
    ]:
        conn.execute(
            sa.text(
                """
                INSERT INTO lifecycle_template (
                    tenant_id, entity_type, name, is_default, description,
                    definition, created_at, updated_at
                )
                SELECT t.id,
                       CAST('change_request' AS VARCHAR),
                       CAST(:name AS VARCHAR),
                       CAST(:is_default AS BOOLEAN),
                       CAST(:description AS TEXT),
                       CAST(:definition AS JSON),
                       now(), now()
                FROM tenant t
                WHERE NOT EXISTS (
                    SELECT 1 FROM lifecycle_template lt
                    WHERE lt.tenant_id = t.id
                      AND lt.entity_type = 'change_request'
                      AND lt.name = CAST(:name AS VARCHAR)
                      AND lt.deleted_at IS NULL
                )
                """
            ),
            {
                "name": name,
                "is_default": is_default,
                "description": description,
                "definition": json.dumps(definition),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    if "lifecycle_template" not in Inspector.from_engine(conn).get_table_names():
        return
    conn.execute(
        sa.text(
            "DELETE FROM lifecycle_template WHERE entity_type = 'change_request' "
            "AND name IN ('Simple Approval', 'Emergency')"
        )
    )
