"""Backfill: set is_failed on default release lifecycle terminal states for existing tenants.

Run once after Phase 5 SP2 lands. Idempotent — only touches the known default state keys
(completed_with_issues, backed_out) on release templates; leaves customized states alone.

Usage:
    cd backend
    uv run python scripts/backfill_release_failed_flags.py
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.db.models.lifecycle import LifecycleTemplate

FAILED_KEYS = {"completed_with_issues", "backed_out"}


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    updated = 0
    async with sessionmaker() as db:
        tpls = (await db.execute(
            select(LifecycleTemplate).where(LifecycleTemplate.entity_type == "release")
        )).scalars().all()
        for tpl in tpls:
            definition = dict(tpl.definition or {})
            states = definition.get("states", [])
            changed = False
            for s in states:
                if s.get("key") in FAILED_KEYS and s.get("is_terminal") and not s.get("is_failed"):
                    s["is_failed"] = True
                    changed = True
            if changed:
                definition["states"] = states
                tpl.definition = definition
                # JSON column: reassign so SQLAlchemy detects the change
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(tpl, "definition")
                updated += 1
        await db.commit()
    await engine.dispose()
    print(f"Updated is_failed on {updated} release lifecycle templates.")


if __name__ == "__main__":
    asyncio.run(main())
