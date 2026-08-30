"""
TDD tests for pir_service (Phase 5 SP4).

Factories mirror test_dora_service.py (_release_template, Release construction)
and test_incident_service.py (Incident direct construction pattern).

The incident-link tests that used to live here moved with their subject when
`pirbackfill` retired `PIR.incident_id`. The rules they pinned are all still
pinned, in `tests/services/test_pir_citation_service.py`: cross-tenant refusal
(`test_an_incident_from_another_tenant_cannot_be_cited`), clearing the link
(`test_removing_a_citation_hard_deletes_it`), and the batched review status
(`test_review_status_*`, `test_the_status_map_answers_only_for_cited_incidents`).
"""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from app.services import pir_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate
from app.db.models.release import Release
from app.db.models.lifecycle import LifecycleTemplate

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Inline factories (mirror sibling test patterns)
# ---------------------------------------------------------------------------

_rel_counter = 0


async def _make_release_template(db, tenant_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name="RT",
        description="",
        is_default=True,
        is_system=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db.add(tpl)
    await db.flush()
    return tpl


@pytest.fixture
def rel_factory(db_session, tenant, user):
    """Async factory that creates a Release for (tenant, user)."""
    tpl_holder = {}

    async def _factory():
        global _rel_counter
        _rel_counter += 1
        if "tpl" not in tpl_holder:
            tpl_holder["tpl"] = await _make_release_template(db_session, tenant.id)
        r = Release(
            tenant_id=tenant.id,
            name=f"Release-{_rel_counter}",
            release_type="Major",
            release_kind="project",
            lifecycle_template_id=tpl_holder["tpl"].id,
            status="draft",
            raised_by=user.id,
        )
        db_session.add(r)
        await db_session.flush()
        return r

    return _factory


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_and_get_for_release(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    pir = await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(summary="s"), user.id)
    assert pir.status == "draft"
    got = await pir_service.get_for_release(db_session, tenant.id, rel.id)
    assert got.id == pir.id


@pytest.mark.asyncio
async def test_duplicate_create_409(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    with pytest.raises(HTTPException) as e:
        await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_create_unknown_release_404(db_session, tenant, user):
    with pytest.raises(HTTPException) as e:
        await pir_service.create_for_release(db_session, tenant.id, 999999, PIRCreate(), user.id)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_complete_sets_and_clears_completed_at(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    p = await pir_service.update(db_session, tenant.id, rel.id, PIRUpdate(status="complete"))
    assert p.completed_at is not None
    p = await pir_service.update(db_session, tenant.id, rel.id, PIRUpdate(status="draft"))
    assert p.completed_at is None


@pytest.mark.asyncio
async def test_soft_delete_allows_recreate(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    await pir_service.delete(db_session, tenant.id, rel.id)
    assert await pir_service.get_for_release(db_session, tenant.id, rel.id) is None
    # recreate must succeed (soft-deleted one doesn't block)
    again = await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    assert again.id is not None


# ---------------------------------------------------------------------------
# Review-recommended coverage tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_for_release_tenant_isolation(db_session, tenant, user, rel_factory):
    """A PIR created under tenant A is NOT returned when queried with a different tenant_id."""
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    # Query with a different (non-existent) tenant_id — must return None
    result = await pir_service.get_for_release(db_session, tenant.id + 9999, rel.id)
    assert result is None
