"""Seed the three default release lifecycle templates + release event types.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill.
Idempotent: safe to call multiple times per tenant.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release_event import ReleaseEventType


_MAJOR_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                 "label": "Draft",                 "is_initial": True,  "is_terminal": False},
        {"key": "submitted",             "label": "Submitted",             "is_initial": False, "is_terminal": False},
        {"key": "approved",              "label": "Approved",              "is_initial": False, "is_terminal": False},
        {"key": "in_progress",           "label": "In Progress",           "is_initial": False, "is_terminal": False},
        {"key": "ready_for_release",     "label": "Ready for Release",     "is_initial": False, "is_terminal": False},
        {"key": "completed",             "label": "Completed",             "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True},
        {"key": "rejected",              "label": "Rejected",              "is_initial": False, "is_terminal": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "submitted",             "allowed_roles": ["Admin", "ReleaseManager", "Developer"]},
        {"from_state": "submitted",         "to_state": "approved",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted",         "to_state": "rejected",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":             {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "description": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "release_type": {"editable_by": ["Admin","ReleaseManager","Developer"]}, "target_date": {"editable_by": ["Admin","ReleaseManager","Developer"]}}, "custom_fields": {}},
        "submitted":         {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name", "release_type", "target_date"]},
        "approved":          {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "in_progress":       {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "ready_for_release": {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "completed":             {"standard_fields": {}, "custom_fields": {}},
        "completed_with_issues": {"standard_fields": {}, "custom_fields": {}},
        "backed_out":            {"standard_fields": {}, "custom_fields": {}},
        "rejected":              {"standard_fields": {}, "custom_fields": {}},
        "cancelled":             {"standard_fields": {}, "custom_fields": {}},
    },
}


_MINOR_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                 "label": "Draft",                 "is_initial": True,  "is_terminal": False},
        {"key": "approved",              "label": "Approved",              "is_initial": False, "is_terminal": False},
        {"key": "in_progress",           "label": "In Progress",           "is_initial": False, "is_terminal": False},
        {"key": "ready_for_release",     "label": "Ready for Release",     "is_initial": False, "is_terminal": False},
        {"key": "completed",             "label": "Completed",             "is_initial": False, "is_terminal": True},
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "approved",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":             {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "approved":          {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name", "target_date"]},
        "in_progress":       {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "ready_for_release": {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "completed":             {"standard_fields": {}, "custom_fields": {}},
        "completed_with_issues": {"standard_fields": {}, "custom_fields": {}},
        "backed_out":            {"standard_fields": {}, "custom_fields": {}},
        "cancelled":             {"standard_fields": {}, "custom_fields": {}},
    },
}


_EMERGENCY_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",      "label": "Draft",      "is_initial": True,  "is_terminal": False},
        {"key": "approved",   "label": "Approved",   "is_initial": False, "is_terminal": False},
        {"key": "in_progress","label": "In Progress","is_initial": False, "is_terminal": False},
        {"key": "completed",  "label": "Completed",  "is_initial": False, "is_terminal": True},
        {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True},
        {"key": "cancelled",  "label": "Cancelled",  "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",       "to_state": "approved",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "in_progress","allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "completed",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "backed_out", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",       "to_state": "cancelled",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "cancelled",  "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":       {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "approved":    {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}, "required_fields": ["name"]},
        "in_progress": {"standard_fields": {}, "custom_fields": {}},
        "completed":   {"standard_fields": {}, "custom_fields": {}},
        "backed_out":  {"standard_fields": {}, "custom_fields": {}},
        "cancelled":   {"standard_fields": {}, "custom_fields": {}},
    },
}


_DEFAULT_LIFECYCLES: list[dict[str, Any]] = [
    {"name": "Major",     "is_default": True,  "description": "Full governance (waterfall-shaped)", "definition": _MAJOR_DEFINITION},
    {"name": "Minor",     "is_default": False, "description": "Light approval",                     "definition": _MINOR_DEFINITION},
    {"name": "Emergency", "is_default": False, "description": "Fast-track",                         "definition": _EMERGENCY_DEFINITION},
]


_DEFAULT_EVENT_TYPES: list[dict[str, Any]] = [
    {"name": "Reschedule Reason",     "display_color": "#ed6c02"},
    {"name": "Scope Change",          "display_color": "#1976d2"},
    {"name": "Stakeholder Note",      "display_color": "#2e7d32"},
    {"name": "Post-Go-Live Incident", "display_color": "#d32f2f"},
]


async def seed_release_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    existing_lifecycle_names = {
        r.name for r in (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.tenant_id == tenant_id,
                    LifecycleTemplate.entity_type == "release",
                )
            )
        ).scalars().all()
    }
    for cfg in _DEFAULT_LIFECYCLES:
        if cfg["name"] in existing_lifecycle_names:
            continue
        db.add(LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type="release",
            name=cfg["name"],
            description=cfg["description"],
            is_default=cfg["is_default"],
            definition=cfg["definition"],
        ))

    existing_event_type_names = {
        r.name for r in (
            await db.execute(
                select(ReleaseEventType).where(ReleaseEventType.tenant_id == tenant_id)
            )
        ).scalars().all()
    }
    for cfg in _DEFAULT_EVENT_TYPES:
        if cfg["name"] in existing_event_type_names:
            continue
        db.add(ReleaseEventType(
            tenant_id=tenant_id,
            name=cfg["name"],
            display_color=cfg["display_color"],
            is_system=True,
        ))
