"""One-off backfill: inject `label` into each transition in existing release
lifecycle templates whose seed predates the schema's `label` requirement.

Labels are derived from a best-guess map keyed on `to_state`; transitions to
`cancelled` always become "Cancel". If a transition already has a non-empty
label, it is left alone.

Safe to run repeatedly.
"""
import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.db.models.lifecycle import LifecycleTemplate


_TO_STATE_LABEL = {
    "submitted": "Submit for Approval",
    "approved": "Approve",
    "rejected": "Reject",
    "in_progress": "Start Release",
    "ready_for_release": "Mark Ready",
    "completed": "Complete",
    "completed_with_issues": "Complete with Issues",
    "backed_out": "Back Out",
    "cancelled": "Cancel",
}


def _label_for(transition: dict[str, Any]) -> str:
    existing = (transition.get("label") or "").strip()
    if existing:
        return existing
    to_state = transition.get("to_state", "")
    return _TO_STATE_LABEL.get(to_state) or to_state.replace("_", " ").title() or "Transition"


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    patched = 0
    async with sessionmaker() as db:
        rows = (
            await db.execute(
                select(LifecycleTemplate).where(
                    LifecycleTemplate.entity_type == "release",
                    LifecycleTemplate.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for tpl in rows:
            definition = dict(tpl.definition or {})
            transitions = list(definition.get("transitions") or [])
            changed = False
            for t in transitions:
                new_label = _label_for(t)
                if t.get("label") != new_label:
                    t["label"] = new_label
                    changed = True
            if changed:
                definition["transitions"] = transitions
                tpl.definition = definition
                flag_modified(tpl, "definition")
                patched += 1
        await db.commit()
    await engine.dispose()
    print(f"Patched {patched} release lifecycle template(s).")


if __name__ == "__main__":
    asyncio.run(main())
