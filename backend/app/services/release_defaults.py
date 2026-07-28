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
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "rejected",              "label": "Rejected",              "is_initial": False, "is_terminal": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "submitted",             "label": "Submit for Approval",  "allowed_roles": ["Admin", "ReleaseManager", "Developer"]},
        {"from_state": "submitted",         "to_state": "approved",              "label": "Approve",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "submitted",         "to_state": "rejected",              "label": "Reject",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "label": "Start Release",        "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "label": "Mark Ready",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "label": "Complete",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "label": "Complete with Issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "label": "Back Out",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
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
        {"key": "completed_with_issues", "label": "Completed with Issues", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "backed_out",            "label": "Backed Out",            "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "cancelled",             "label": "Cancelled",             "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",             "to_state": "approved",              "label": "Approve",              "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "in_progress",           "label": "Start Release",        "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "ready_for_release",     "label": "Mark Ready",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed",             "label": "Complete",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "completed_with_issues", "label": "Complete with Issues", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "ready_for_release", "to_state": "backed_out",            "label": "Back Out",             "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",             "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",          "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress",       "to_state": "cancelled",             "label": "Cancel",               "allowed_roles": ["Admin", "ReleaseManager"]},
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
        {"key": "backed_out", "label": "Backed Out", "is_initial": False, "is_terminal": True, "is_failed": True},
        {"key": "cancelled",  "label": "Cancelled",  "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",       "to_state": "approved",    "label": "Approve",       "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "in_progress", "label": "Start Release", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "completed",   "label": "Complete",      "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "in_progress", "to_state": "backed_out",  "label": "Back Out",      "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",       "to_state": "cancelled",   "label": "Cancel",        "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "approved",    "to_state": "cancelled",   "label": "Cancel",        "allowed_roles": ["Admin", "ReleaseManager"]},
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


_ENTERPRISE_DEFINITION: dict[str, Any] = {
    "states": [
        {"key": "draft",                "label": "Draft",               "is_initial": True,  "is_terminal": False},
        {"key": "planning",             "label": "Planning",            "is_initial": False, "is_terminal": False},
        {"key": "admission_open",       "label": "Admission Open",      "is_initial": False, "is_terminal": False},
        {"key": "admission_closed",     "label": "Admission Closed",    "is_initial": False, "is_terminal": False, "is_admission_lockdown": True},
        {"key": "integration_testing",  "label": "Integration Testing", "is_initial": False, "is_terminal": False},
        {"key": "uat",                  "label": "UAT",                 "is_initial": False, "is_terminal": False},
        {"key": "staging",              "label": "Staging",             "is_initial": False, "is_terminal": False},
        {"key": "cab",                  "label": "CAB",                 "is_initial": False, "is_terminal": False},
        {"key": "deploying",            "label": "Deploying",           "is_initial": False, "is_terminal": False},
        {"key": "deployed",             "label": "Deployed",            "is_initial": False, "is_terminal": True},
        {"key": "cancelled",            "label": "Cancelled",           "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        {"from_state": "draft",              "to_state": "planning",             "label": "Start Planning",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "planning",           "to_state": "admission_open",       "label": "Open Admissions",  "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_open",     "to_state": "admission_closed",     "label": "Close Admissions", "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_closed",   "to_state": "integration_testing",  "label": "Start IT",         "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "integration_testing","to_state": "uat",                  "label": "Promote to UAT",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "uat",                "to_state": "staging",              "label": "Promote to Stg",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "staging",            "to_state": "cab",                  "label": "Submit for CAB",   "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "cab",                "to_state": "deploying",            "label": "Start Deploy",     "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "deploying",          "to_state": "deployed",             "label": "Deployed",         "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "draft",              "to_state": "cancelled",            "label": "Cancel",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "planning",           "to_state": "cancelled",            "label": "Cancel",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_open",     "to_state": "cancelled",            "label": "Cancel",           "allowed_roles": ["Admin", "ReleaseManager"]},
        {"from_state": "admission_closed",   "to_state": "cancelled",            "label": "Cancel",           "allowed_roles": ["Admin", "ReleaseManager"]},
    ],
    "field_permissions": {
        "draft":               {"standard_fields": {"name": {"editable_by": ["Admin","ReleaseManager"]}, "description": {"editable_by": ["Admin","ReleaseManager"]}, "release_type": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "planning":            {"standard_fields": {"description": {"editable_by": ["Admin","ReleaseManager"]}, "target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "admission_open":      {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "admission_closed":    {"standard_fields": {"target_date": {"editable_by": ["Admin","ReleaseManager"]}}, "custom_fields": {}},
        "integration_testing": {"standard_fields": {}, "custom_fields": {}},
        "uat":                 {"standard_fields": {}, "custom_fields": {}},
        "staging":             {"standard_fields": {}, "custom_fields": {}},
        "cab":                 {"standard_fields": {}, "custom_fields": {}},
        "deploying":           {"standard_fields": {}, "custom_fields": {}},
        "deployed":            {"standard_fields": {}, "custom_fields": {}},
        "cancelled":           {"standard_fields": {}, "custom_fields": {}},
    },
    "action_permissions": {
        state: {
            "membership.admit":  ["Admin", "ReleaseManager"],
            "membership.reject": ["Admin", "ReleaseManager"],
            "membership.remove": ["Admin", "ReleaseManager"],
        }
        for state in (
            "draft", "planning", "admission_open", "admission_closed",
            "integration_testing", "uat", "staging", "cab", "deploying"
        )
    },
}


_DEFAULT_LIFECYCLES: list[dict[str, Any]] = [
    {"name": "Major",     "is_default": True,  "applies_to_kind": "project",    "description": "Full governance (waterfall-shaped)", "definition": _MAJOR_DEFINITION},
    {"name": "Minor",     "is_default": False, "applies_to_kind": "project",    "description": "Light approval",                     "definition": _MINOR_DEFINITION},
    {"name": "Emergency", "is_default": False, "applies_to_kind": "project",    "description": "Fast-track",                         "definition": _EMERGENCY_DEFINITION},
    {"name": "Enterprise Release — default", "is_default": True, "applies_to_kind": "enterprise", "description": "Multi-team enterprise release lifecycle", "definition": _ENTERPRISE_DEFINITION},
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
            applies_to_kind=cfg["applies_to_kind"],
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
