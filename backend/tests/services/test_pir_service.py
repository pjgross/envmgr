"""
TDD tests for pir_service (Phase 5 SP4).

Factories mirror test_dora_service.py (_release_template, Release construction)
and test_incident_service.py (Incident direct construction pattern).
"""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from app.services import pir_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate
from app.db.models.release import Release
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Inline factories (mirror sibling test patterns)
# ---------------------------------------------------------------------------

_rel_counter = 0
_inc_counter = 0


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


@pytest.fixture
def incident_factory(db_session, tenant):
    """Async factory that creates a bare Incident for tenant."""
    async def _factory():
        global _inc_counter
        _inc_counter += 1
        inc = Incident(
            tenant_id=tenant.id,
            title=f"Incident-{_inc_counter}",
            severity="P1",
            status="new",
            detected_at=datetime.now(UTC),
            source="manual",
        )
        db_session.add(inc)
        await db_session.flush()
        return inc

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


@pytest.mark.asyncio
async def test_pir_status_for_incidents_bulk(db_session, tenant, user, rel_factory, incident_factory):
    inc = await incident_factory()
    rel = await rel_factory()
    await pir_service.create_for_release(
        db_session, tenant.id, rel.id,
        PIRCreate(incident_id=inc.id, status="complete"), user.id
    )
    m = await pir_service.pir_status_for_incidents(db_session, tenant.id, [inc.id, 999999])
    assert m.get(inc.id) == "complete" and 999999 not in m
