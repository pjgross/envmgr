"""The default environment-request lifecycle seeded into every tenant.

Deliberately plain. A tenant wanting a second review step edits it in the
existing admin UI — which is the entire reason B3b reuses lifecycle templates
rather than a fixed status enum.

The ROLE gate lives here. The GROUP gate does not: it is applied on top by
environment_request_service.assert_may_transition, because the template has no
way to express "a member of the target environment's operating team".
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate

ENTITY_TYPE = "environment_request"

_ALL_ROLES = ["Admin", "Release Manager", "Test Manager", "Developer", "Viewer"]
_APPROVER_ROLES = ["Admin", "Release Manager", "Test Manager"]

DEFAULT_REQUEST_LIFECYCLE: dict[str, Any] = {
    "states": [
        {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
        {"key": "submitted", "label": "Submitted", "is_initial": False, "is_terminal": False},
        {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
        {"key": "fulfilled", "label": "Fulfilled", "is_initial": False, "is_terminal": True},
        {"key": "rejected", "label": "Rejected", "is_initial": False, "is_terminal": True},
        {"key": "cancelled", "label": "Cancelled", "is_initial": False, "is_terminal": True},
    ],
    "transitions": [
        # Anyone may raise and submit a request — including a Viewer, who is
        # exactly the person most likely to need access to an environment.
        {"from_state": "draft", "to_state": "submitted", "label": "Submit",
         "allowed_roles": _ALL_ROLES},
        {"from_state": "draft", "to_state": "cancelled", "label": "Cancel",
         "allowed_roles": _ALL_ROLES},
        # I6: a requester who changes their mind must be able to withdraw
        # their own submitted request without finding an approver — same
        # roles as draft -> cancelled, and 'cancelled' is not an
        # APPROVAL_TARGET_STATE, so this is unaffected by the group gate the
        # same way draft -> submitted already is.
        {"from_state": "submitted", "to_state": "cancelled", "label": "Cancel",
         "allowed_roles": _ALL_ROLES},
        {"from_state": "submitted", "to_state": "approved", "label": "Approve",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "submitted", "to_state": "rejected", "label": "Reject",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "submitted", "to_state": "draft", "label": "Return for Revision",
         "allowed_roles": _APPROVER_ROLES},
        {"from_state": "approved", "to_state": "fulfilled", "label": "Mark Fulfilled",
         "allowed_roles": _APPROVER_ROLES},
        # C2: 'approved' otherwise has exactly one outgoing edge. A request
        # that reaches 'approved' and then can never be fulfilled (a
        # proposed_name clash with an existing environment, discovered only
        # at fulfilment) had no way out at all — approved -> rejected gives
        # it one, mirroring submitted -> rejected's role gate.
        {"from_state": "approved", "to_state": "rejected", "label": "Reject",
         "allowed_roles": _APPROVER_ROLES},
    ],
    "field_permissions": {},
}

_TEMPLATE_NAME = "Standard Request"


async def seed_environment_request_defaults_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    """Idempotent per (tenant, template name), matching the other seeders."""
    existing = (
        await db.execute(
            select(LifecycleTemplate.id).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == ENTITY_TYPE,
                LifecycleTemplate.name == _TEMPLATE_NAME,
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).first()
    if existing is not None:
        return

    db.add(
        LifecycleTemplate(
            tenant_id=tenant_id,
            entity_type=ENTITY_TYPE,
            name=_TEMPLATE_NAME,
            description="Raise, approve and fulfil environment requests.",
            is_default=True,
            is_system=False,
            definition=DEFAULT_REQUEST_LIFECYCLE,
        )
    )
    await db.flush()
