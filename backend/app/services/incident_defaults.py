"""Seed the default incident lifecycle template. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate

ALL_ROLES = ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]


def _t(frm: str, to: str, label: str) -> dict:
    return {"from_state": frm, "to_state": to, "label": label, "allowed_roles": ALL_ROLES}


_INCIDENT_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "new",           "label": "New",           "is_initial": True,  "is_terminal": False},
        {"key": "investigating", "label": "Investigating", "is_initial": False, "is_terminal": False},
        {"key": "identified",    "label": "Identified",    "is_initial": False, "is_terminal": False},
        {"key": "fix_scheduled", "label": "Fix Scheduled", "is_initial": False, "is_terminal": False},
        {"key": "resolved",      "label": "Resolved",      "is_initial": False, "is_terminal": False, "is_resolved": True},
        {"key": "closed",        "label": "Closed",        "is_initial": False, "is_terminal": True},
        {"key": "cancelled",     "label": "Cancelled",     "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        _t("new", "investigating", "Start Investigating"),
        _t("investigating", "identified", "Root Cause Identified"),
        _t("identified", "fix_scheduled", "Schedule Fix"),
        _t("fix_scheduled", "resolved", "Mark Resolved"),
        _t("identified", "resolved", "Mark Resolved"),
        _t("investigating", "resolved", "Mark Resolved"),
        _t("resolved", "closed", "Close"),
        _t("resolved", "investigating", "Reopen"),
        _t("new", "cancelled", "Cancel"),
        _t("investigating", "cancelled", "Cancel"),
        _t("identified", "cancelled", "Cancel"),
    ],
    "field_permissions": {
        s: {
            "standard_fields": {
                "title": {"editable_by": ALL_ROLES},
                "description": {"editable_by": ALL_ROLES},
                "severity": {"editable_by": ALL_ROLES},
            },
            "custom_fields": {},
        }
        for s in ("new", "investigating", "identified", "fix_scheduled", "resolved", "closed", "cancelled")
    },
}


async def seed_incident_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    existing = {
        r.name for r in (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == "incident",
                )
            )
        ).scalars().all()
    }
    if "Default Incident Lifecycle" in existing:
        return
    db.add(LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="incident",
        name="Default Incident Lifecycle",
        description="Default incident state machine",
        is_default=True,
        is_system=True,
        definition=_INCIDENT_DEFINITION,
    ))
