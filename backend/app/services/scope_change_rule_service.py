"""Service layer for ScopeChangeKindRule — per-tenant admin config that
determines which change_kind values on ReleaseChange count as "scope changes"
for release-level reporting.

Seeded with four standard kinds at tenant creation. Only `story` defaults to
counts_as_scope_change=True; the other three are False so e.g. test bugs
aren't treated as scope churn when they're added to a release.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.scope_change_kind_rule import ScopeChangeKindRule


# The canonical set of change_kind values the frontend exposes. Kept in sync
# with frontend/src/components/releases/ScopeItemDialog.tsx.
DEFAULT_KINDS: tuple[str, ...] = ("story", "defect", "task", "spike")

# Default counts_as_scope_change value per kind at tenant creation.
DEFAULT_RULES: dict[str, bool] = {
    "story": True,
    "defect": False,
    "task": False,
    "spike": False,
}


async def seed_default_rules(db: AsyncSession, tenant_id: int) -> None:
    """Create the four standard kind rules for a tenant. Called from
    tenant_service.create_tenant. Idempotent: skips kinds that already have
    an active rule."""
    existing = (
        await db.execute(
            select(ScopeChangeKindRule.change_kind).where(
                ScopeChangeKindRule.tenant_id == tenant_id,
                ScopeChangeKindRule.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    existing_set = set(existing)
    for kind in DEFAULT_KINDS:
        if kind in existing_set:
            continue
        db.add(
            ScopeChangeKindRule(
                tenant_id=tenant_id,
                change_kind=kind,
                counts_as_scope_change=DEFAULT_RULES.get(kind, True),
            )
        )
    await db.flush()


async def list_rules(db: AsyncSession, tenant_id: int) -> list[ScopeChangeKindRule]:
    """Return all active rules for a tenant, ordered by change_kind."""
    result = await db.execute(
        select(ScopeChangeKindRule)
        .where(
            ScopeChangeKindRule.tenant_id == tenant_id,
            ScopeChangeKindRule.deleted_at.is_(None),
        )
        .order_by(ScopeChangeKindRule.change_kind)
    )
    return list(result.scalars().all())


async def load_rule_map(
    db: AsyncSession, tenant_id: int
) -> dict[str, bool]:
    """Return {change_kind: counts_as_scope_change} for the tenant. Kinds
    without an explicit rule default to True (safer fallback: a newly-added
    kind counts until an admin opts it out)."""
    rows = await list_rules(db, tenant_id)
    return {r.change_kind: r.counts_as_scope_change for r in rows}


async def upsert_rules(
    db: AsyncSession,
    tenant_id: int,
    rules: list[tuple[str, bool]],
) -> list[ScopeChangeKindRule]:
    """Apply a batch of (change_kind, counts_as_scope_change) updates.
    Creates missing rows, updates existing ones. Returns the full rule list."""
    existing = {
        r.change_kind: r
        for r in await list_rules(db, tenant_id)
    }
    for kind, counts in rules:
        row = existing.get(kind)
        if row is None:
            db.add(
                ScopeChangeKindRule(
                    tenant_id=tenant_id,
                    change_kind=kind,
                    counts_as_scope_change=counts,
                )
            )
        else:
            row.counts_as_scope_change = counts
    await db.flush()
    return await list_rules(db, tenant_id)


def counts_for_kind(rules: dict[str, bool], change_kind: Optional[str]) -> bool:
    """Pure-function resolver: does this change_kind count as a scope change?
    Defaults to True when the kind is unknown (matches load_rule_map fallback)."""
    if change_kind is None:
        return False
    return rules.get(change_kind, True)
