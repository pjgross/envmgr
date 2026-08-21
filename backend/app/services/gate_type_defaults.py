"""Seed the eight standard release-gate types. Idempotent per tenant.

Called by tenant_service.create_tenant() and exposed for per-tenant backfill,
following environment_tier_defaults.py and release_defaults.py.

The migration carries its own literal copy of this list rather than importing
it. That is deliberate: a migration reproduces the past, so it must not change
meaning when this module gains a ninth type.
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.gate_type import GateType

STANDARD_GATE_TYPES: list[dict[str, Any]] = [
    {"name": "Functional",     "category": "functional",     "failure_behaviour": "block",
     "expected_evidence": ["Test execution report", "Defect summary"],
     "requires_deployment_link": True,  "display_order": 10},
    {"name": "NFR / Performance", "category": "nfr",         "failure_behaviour": "block",
     "expected_evidence": ["Performance test report"],
     "requires_deployment_link": True,  "display_order": 20},
    {"name": "Integration",    "category": "integration",    "failure_behaviour": "block",
     "expected_evidence": ["Integration test report"],
     "requires_deployment_link": True,  "display_order": 30},
    {"name": "Security",       "category": "security",       "failure_behaviour": "block",
     "expected_evidence": ["Security scan result"],
     "requires_deployment_link": True,  "display_order": 40},
    {"name": "License",        "category": "license",        "failure_behaviour": "warn",
     "expected_evidence": ["Dependency licence report"],
     "requires_deployment_link": False, "display_order": 50},
    {"name": "Accessibility",  "category": "accessibility",  "failure_behaviour": "warn",
     "expected_evidence": ["Accessibility audit"],
     "requires_deployment_link": False, "display_order": 60},
    {"name": "Business",       "category": "business",       "failure_behaviour": "accept_with_exception",
     "expected_evidence": ["Business sign-off"],
     "requires_deployment_link": False, "display_order": 70},
    {"name": "Ops Readiness",  "category": "ops_readiness",  "failure_behaviour": "block",
     "expected_evidence": ["Runbook", "Monitoring confirmation"],
     "requires_deployment_link": False, "display_order": 80},
]


async def seed_gate_type_defaults_for_tenant(db: AsyncSession, tenant_id: int) -> None:
    """Create any of the standard gate types this tenant does not already have.

    Matched on lowercased name so a tenant that already has 'security' is not
    given a second 'Security'.
    """
    existing = {
        name.lower()
        for name in (
            await db.execute(
                select(GateType.name).where(GateType.tenant_id == tenant_id)
            )
        ).scalars().all()
    }
    for spec in STANDARD_GATE_TYPES:
        if spec["name"].lower() in existing:
            continue
        db.add(GateType(tenant_id=tenant_id, is_active=True, **spec))
