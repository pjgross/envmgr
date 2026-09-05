"""Seed the three standard Go/No-Go perspectives. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following gate_type_defaults.py.

The migration carries its own literal copy of this list rather than importing
it. That is deliberate: a migration reproduces the past, so it must not change
meaning when this module gains a fourth perspective.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.go_no_go import GoNoGoPerspective

STANDARD_PERSPECTIVES: list[dict[str, Any]] = [
    {"name": "Quality",    "sort_order": 10,
     "description": "Test coverage, defects and quality evidence. Typically the Test Manager."},
    {"name": "Process",    "sort_order": 20,
     "description": "Gates, change process and readiness. Typically the Release Manager."},
    {"name": "Acceptance", "sort_order": 30,
     "description": "Business acceptance of the change and its risk. Typically the sponsor."},
]


async def seed_go_no_go_perspective_defaults_for_tenant(
    db: AsyncSession, tenant_id: int
) -> None:
    existing = set(
        (
            await db.execute(
                select(GoNoGoPerspective.name).where(GoNoGoPerspective.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    for spec in STANDARD_PERSPECTIVES:
        if spec["name"] in existing:
            continue
        db.add(GoNoGoPerspective(tenant_id=tenant_id, is_active=True, **spec))
    await db.flush()
