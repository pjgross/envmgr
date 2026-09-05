"""Phase 9 C3 — Go/No-Go decision record."""
import pytest

from app.services import go_no_go_defaults
from app.db.models.go_no_go import GoNoGoPerspective


@pytest.mark.asyncio
async def test_seeding_is_idempotent(db_session, test_tenant):
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    await go_no_go_defaults.seed_go_no_go_perspective_defaults_for_tenant(
        db_session, test_tenant.id
    )
    from sqlalchemy import select
    rows = (await db_session.execute(
        select(GoNoGoPerspective).where(GoNoGoPerspective.tenant_id == test_tenant.id)
    )).scalars().all()
    assert [r.name for r in rows] == ["Quality", "Process", "Acceptance"]
