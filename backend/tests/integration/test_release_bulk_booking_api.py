import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.base import get_db
from app.db.models.system import System
from app.db.models.environment import Environment, EnvironmentSystem
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking import Booking, ContextTag
from app.db.models.booking_request import BookingRequest
from app.db.models.environment_decommission import EnvironmentDecommission
from tests.factories import ensure_environment_tier

WIN_START = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
WIN_END = WIN_START + timedelta(days=1)


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123", "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


async def _make_release(authed_client, release_lifecycle_template) -> int:
    r = await authed_client.post("/api/v1/releases", json={
        "name": "Rel", "release_type": "Test Major", "release_kind": "project",
        "lifecycle_template_id": release_lifecycle_template.id,
    })
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_system(db_session, tenant_id, name) -> int:
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s.id


async def _make_env(db_session, tenant_id, name) -> int:
    tier = await ensure_environment_tier(db_session, tenant_id)
    e = Environment(tenant_id=tenant_id, name=name, tier_id=tier.id)
    db_session.add(e)
    await db_session.flush()
    return e.id


async def _host(db_session, tenant_id, env_id, system_id):
    db_session.add(EnvironmentSystem(tenant_id=tenant_id, environment_id=env_id, system_id=system_id))
    await db_session.flush()


async def _link(authed_client, rid, sid, role):
    resp = await authed_client.post(f"/api/v1/releases/{rid}/systems", json={"system_id": sid, "role": role})
    assert resp.status_code == 201, resp.text


async def _booking_type(db_session, tenant_id) -> int:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="booking", name="bt-lc",
        definition={
            "states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
            "transitions": [], "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    bt = BookingType(tenant_id=tenant_id, name="Standard", lifecycle_template_id=tpl.id)
    db_session.add(bt)
    await db_session.flush()
    return bt.id


def _payload(env_ids, bt, **extra):
    return {
        "environment_ids": env_ids,
        "start": WIN_START.isoformat(),
        "end": WIN_END.isoformat(),
        "booking_type_id": bt,
        **extra,
    }


@pytest.mark.asyncio
async def test_bulk_books_all_free_environments(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    b = await _make_env(db_session, tenant.id, "B")
    c = await _make_env(db_session, tenant.id, "C")

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, b, c], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {x["environment_id"] for x in body["created"]} == {a, b, c}
    assert body["skipped"] == []
    for item in body["created"]:
        assert item["booking_id"] > 0
        assert item["warnings"] == []


@pytest.mark.asyncio
async def test_bulk_sets_context_tag_from_role(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    sysid = await _make_system(db_session, tenant.id, "Payments")
    await _link(authed_client, rid, sysid, "changing")
    env = await _make_env(db_session, tenant.id, "A")
    await _host(db_session, tenant.id, env, sysid)

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([env], bt))
    assert resp.status_code == 200, resp.text
    booking_id = resp.json()["created"][0]["booking_id"]
    booking = (await db_session.execute(select(Booking).where(Booking.id == booking_id))).scalar_one()
    br = (await db_session.execute(
        select(BookingRequest).where(BookingRequest.id == booking.booking_request_id)
    )).scalar_one()
    assert br.context_tag == ContextTag.DEPLOYMENT


@pytest.mark.asyncio
async def test_bulk_skips_exclusive_conflict(authed_client, tenant, user, db_session, release_lifecycle_template):
    from app.services.release_booking_service import book_environment_for_phase
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    b = await _make_env(db_session, tenant.id, "B")

    pre = await book_environment_for_phase(
        db_session, release_id=rid, phase_id=None, environment_id=a,
        start=WIN_START, end=WIN_END, booking_type_id=bt, tenant_id=tenant.id,
        user_id=user.id, project_name="pre", exclusive_use=True,
        now=datetime.now(timezone.utc),
    )
    await db_session.flush()

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, b], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {x["environment_id"] for x in body["created"]} == {b}
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["environment_id"] == a
    assert pre.id in body["skipped"][0]["conflicts"]


@pytest.mark.asyncio
async def test_bulk_skips_environment_with_teardown_inside_window_and_reports_why(
    authed_client, tenant, user, db_session, release_lifecycle_template
):
    """B5 fix wave item 1: the decommission refusal `assert_bookable` raises
    is a string-detail HTTPException, not the {"message", "conflicts"} shape
    an exclusive-use overlap raises. `bulk_book_environments` must carry that
    string through as `reason` rather than discarding it into an empty
    `conflicts` list — see release_booking_service.bulk_book_environments."""
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    b = await _make_env(db_session, tenant.id, "B")

    # Teardown lands inside the requested [WIN_START, WIN_END) window, so the
    # booking runs past it and assert_bookable refuses environment A only.
    teardown_at = WIN_START + timedelta(hours=6)
    db_session.add(EnvironmentDecommission(
        tenant_id=tenant.id, environment_id=a, reason="going away",
        warned_at=datetime.now(timezone.utc), scheduled_teardown_at=teardown_at,
        initiated_by=user.id,
    ))
    await db_session.flush()

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, b], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {x["environment_id"] for x in body["created"]} == {b}
    assert len(body["skipped"]) == 1
    skipped = body["skipped"][0]
    assert skipped["environment_id"] == a
    # Not the exclusive-conflict shape: no conflicting booking ids.
    assert skipped["conflicts"] == []
    # The real refusal reason must survive, not an empty conflicts list
    # standing in for "exclusive conflict".
    assert skipped["reason"]
    assert "torn down" in skipped["reason"]


@pytest.mark.asyncio
async def test_bulk_soft_conflict_warns(authed_client, tenant, user, db_session, release_lifecycle_template):
    from app.services.release_booking_service import book_environment_for_phase
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")

    pre = await book_environment_for_phase(
        db_session, release_id=rid, phase_id=None, environment_id=a,
        start=WIN_START, end=WIN_END, booking_type_id=bt, tenant_id=tenant.id,
        user_id=user.id, project_name="pre", exclusive_use=False,
        now=datetime.now(timezone.utc),
    )
    await db_session.flush()

    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["skipped"] == []
    assert len(body["created"]) == 1
    assert pre.id in body["created"][0]["warnings"]


@pytest.mark.asyncio
async def test_bulk_empty_ids_422(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([], bt))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_bulk_unknown_release_404(authed_client, tenant, db_session, release_lifecycle_template):
    bt = await _booking_type(db_session, tenant.id)
    resp = await authed_client.post("/api/v1/releases/999999/bookings/bulk", json=_payload([1], bt))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_bulk_dedupes_duplicate_env_ids(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    a = await _make_env(db_session, tenant.id, "A")
    resp = await authed_client.post(f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([a, a, a], bt))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [x["environment_id"] for x in body["created"]] == [a]  # booked once, not thrice
    assert body["skipped"] == []


@pytest.mark.asyncio
async def test_bulk_sets_release_and_phase_on_bookings(authed_client, tenant, db_session, release_lifecycle_template):
    rid = await _make_release(authed_client, release_lifecycle_template)
    bt = await _booking_type(db_session, tenant.id)
    env = await _make_env(db_session, tenant.id, "A")
    ph = await authed_client.post(f"/api/v1/releases/{rid}/phases", json={"name": "Smoke"})
    assert ph.status_code == 201, ph.text
    phase_id = ph.json()["id"]

    resp = await authed_client.post(
        f"/api/v1/releases/{rid}/bookings/bulk", json=_payload([env], bt, phase_id=phase_id)
    )
    assert resp.status_code == 200, resp.text
    booking_id = resp.json()["created"][0]["booking_id"]
    booking = (await db_session.execute(select(Booking).where(Booking.id == booking_id))).scalar_one()
    assert booking.release_id == rid
    assert booking.test_phase_id == phase_id
