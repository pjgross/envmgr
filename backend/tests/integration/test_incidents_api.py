"""Integration tests for the Incidents API (Phase 5 SP1)."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`, with incident defaults seeded."""
    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.commit()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username,
            "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_incident_crud_and_transition_flow(authed_client):
    # create
    r = await authed_client.post("/api/v1/incidents", json={"title": "Outage", "severity": "P1"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert r.json()["status"] == "new"
    # list
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200 and any(i["id"] == iid for i in r.json())
    # transition
    r = await authed_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "investigating"})
    assert r.status_code == 200 and r.json()["status"] == "investigating"
    # detail
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "investigating"
    assert any(t["to_state"] in ("identified", "resolved") for t in body["allowed_transitions"])
    # delete
    r = await authed_client.delete(f"/api/v1/incidents/{iid}")
    assert r.status_code == 204
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_invalid_transition_returns_422(authed_client):
    iid = (await authed_client.post("/api/v1/incidents", json={"title": "x", "severity": "P3"})).json()["id"]
    r = await authed_client.post(f"/api/v1/incidents/{iid}/transition", json={"to_state": "closed"})
    assert r.status_code == 422


# ── Task 5: PIR integration on incident detail + list ─────────────────────────

@pytest_asyncio.fixture(scope="function")
async def demo_release_id(db_session, tenant, user) -> int:
    """A persisted Release in the test tenant; yields its id."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="Incident PIR Test Release Template",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant.id,
        name="Incident PIR Integration Test Release",
        release_type="Major",
        release_kind="project",
        lifecycle_template_id=tpl.id,
        status="draft",
        raised_by=user.id,
    )
    db_session.add(r)
    await db_session.flush()
    await db_session.commit()
    return r.id


@pytest.mark.asyncio
async def test_incident_detail_has_pir(authed_client, demo_release_id):
    """GET /incidents/{id} includes a `pir` object when a PIR is linked to the incident."""
    # Create incident
    r = await authed_client.post("/api/v1/incidents", json={"title": "PIR Test Outage", "severity": "P2"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    # Detail before PIR — pir should be null
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200
    assert r.json()["pir"] is None

    # Create a complete PIR on demo_release, linked to the incident
    r = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir",
        json={
            "incident_id": iid,
            "status": "complete",
            "summary": "All good",
            "root_cause": "Config drift",
            "action_plan": "Add alerting",
        },
    )
    assert r.status_code == 201, r.text

    # Detail after PIR — pir key should be populated
    r = await authed_client.get(f"/api/v1/incidents/{iid}")
    assert r.status_code == 200, r.text
    body = r.json()
    pir = body.get("pir")
    assert pir is not None, f"Expected 'pir' in detail, got: {body}"
    assert pir["status"] == "complete"
    assert pir["release_id"] == demo_release_id
    assert pir["root_cause"] == "Config drift"
    assert pir["action_plan"] == "Add alerting"
    assert pir["summary"] == "All good"


@pytest.mark.asyncio
async def test_incident_list_has_pir_status(authed_client, demo_release_id):
    """GET /incidents list rows include `pir_status` — 'none' without PIR, 'complete' after."""
    # Create incident
    r = await authed_client.post("/api/v1/incidents", json={"title": "List PIR Test", "severity": "P3"})
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    # List before PIR — pir_status should be "none"
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200
    row = next((i for i in r.json() if i["id"] == iid), None)
    assert row is not None
    assert row["pir_status"] == "none"

    # Create a complete PIR linked to this incident
    r = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir",
        json={"incident_id": iid, "status": "complete"},
    )
    assert r.status_code == 201, r.text

    # List after PIR — pir_status should be "complete"
    r = await authed_client.get("/api/v1/incidents")
    assert r.status_code == 200
    row = next((i for i in r.json() if i["id"] == iid), None)
    assert row is not None, "Incident not found in list"
    assert row["pir_status"] == "complete", f"Expected 'complete', got: {row['pir_status']}"


# ---------------------------------------------------------------------------
# Server-side sorting (sub-project C1 task 3)
# ---------------------------------------------------------------------------


def _t(offset_days: float) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset_days)


@pytest.mark.asyncio
async def test_list_incidents_default_order_unchanged(
    authed_client: AsyncClient, db_session, tenant
):
    """No sort_by: order must stay `detected_at DESC, id` — today's ordering,
    byte for byte.

    Insertion order (a, b, c) deliberately disagrees with both id-ascending and
    detected_at-ascending order, so a response that happened to preserve
    insertion order — or that silently flipped to ascending the moment this
    endpoint gained the sorting() dependency — would not accidentally satisfy
    this assertion.
    """
    a = Incident(tenant_id=tenant.id, title="A", severity="P1", status="new", detected_at=_t(2))
    b = Incident(tenant_id=tenant.id, title="B", severity="P1", status="new", detected_at=_t(0))
    c = Incident(tenant_id=tenant.id, title="C", severity="P1", status="new", detected_at=_t(1))
    db_session.add_all([a, b, c])
    await db_session.flush()

    resp = await authed_client.get("/api/v1/incidents")
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_incidents_sort_by_title_both_directions(
    authed_client: AsyncClient, db_session, tenant
):
    charlie = Incident(tenant_id=tenant.id, title="Charlie", severity="P1", status="new", detected_at=_t(0))
    alpha = Incident(tenant_id=tenant.id, title="Alpha", severity="P1", status="new", detected_at=_t(1))
    bravo = Incident(tenant_id=tenant.id, title="Bravo", severity="P1", status="new", detected_at=_t(2))
    db_session.add_all([charlie, alpha, bravo])
    await db_session.flush()

    asc = await authed_client.get("/api/v1/incidents?sort_by=title&sort_dir=asc")
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, bravo.id, charlie.id]

    desc = await authed_client.get("/api/v1/incidents?sort_by=title&sort_dir=desc")
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [charlie.id, bravo.id, alpha.id]


@pytest.mark.asyncio
async def test_list_incidents_sort_by_severity_both_directions(
    authed_client: AsyncClient, db_session, tenant
):
    """Severities P1-P4 are stored as the literal string (plain String(2)
    column, not a SQLAlchemy Enum) — insertion order below deliberately
    disagrees with severity order so only the sort, not insertion/id order,
    could produce these sequences."""
    p3 = Incident(tenant_id=tenant.id, title="i1", severity="P3", status="new", detected_at=_t(0))
    p1 = Incident(tenant_id=tenant.id, title="i2", severity="P1", status="new", detected_at=_t(1))
    p2 = Incident(tenant_id=tenant.id, title="i3", severity="P2", status="new", detected_at=_t(2))
    db_session.add_all([p3, p1, p2])
    await db_session.flush()

    asc = await authed_client.get("/api/v1/incidents?sort_by=severity&sort_dir=asc")
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [p1.id, p2.id, p3.id]

    desc = await authed_client.get("/api/v1/incidents?sort_by=severity&sort_dir=desc")
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [p3.id, p2.id, p1.id]


@pytest.mark.asyncio
async def test_list_incidents_sort_by_status_both_directions(
    authed_client: AsyncClient, db_session, tenant
):
    mu = Incident(tenant_id=tenant.id, title="i1", severity="P1", status="mu", detected_at=_t(0))
    alpha = Incident(tenant_id=tenant.id, title="i2", severity="P1", status="alpha", detected_at=_t(1))
    zeta = Incident(tenant_id=tenant.id, title="i3", severity="P1", status="zeta", detected_at=_t(2))
    db_session.add_all([mu, alpha, zeta])
    await db_session.flush()

    asc = await authed_client.get("/api/v1/incidents?sort_by=status&sort_dir=asc")
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [alpha.id, mu.id, zeta.id]

    desc = await authed_client.get("/api/v1/incidents?sort_by=status&sort_dir=desc")
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [zeta.id, mu.id, alpha.id]


@pytest.mark.asyncio
async def test_list_incidents_sort_by_detected_at_both_directions(
    authed_client: AsyncClient, db_session, tenant
):
    a = Incident(tenant_id=tenant.id, title="A", severity="P1", status="new", detected_at=_t(2))
    b = Incident(tenant_id=tenant.id, title="B", severity="P1", status="new", detected_at=_t(0))
    c = Incident(tenant_id=tenant.id, title="C", severity="P1", status="new", detected_at=_t(1))
    db_session.add_all([a, b, c])
    await db_session.flush()

    asc = await authed_client.get("/api/v1/incidents?sort_by=detected_at&sort_dir=asc")
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [b.id, c.id, a.id]

    desc = await authed_client.get("/api/v1/incidents?sort_by=detected_at&sort_dir=desc")
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_incidents_sort_by_resolved_at_both_directions(
    authed_client: AsyncClient, db_session, tenant
):
    """All rows get a non-null resolved_at — Postgres defaults NULLs LAST on
    ASC and NULLS FIRST on DESC while SQLite treats NULL as the smallest value,
    so a row with a null resolved_at here would make the two engines disagree
    on the expected sequence."""
    a = Incident(
        tenant_id=tenant.id, title="A", severity="P1", status="new",
        detected_at=_t(0), resolved_at=_t(2),
    )
    b = Incident(
        tenant_id=tenant.id, title="B", severity="P1", status="new",
        detected_at=_t(0), resolved_at=_t(0),
    )
    c = Incident(
        tenant_id=tenant.id, title="C", severity="P1", status="new",
        detected_at=_t(0), resolved_at=_t(1),
    )
    db_session.add_all([a, b, c])
    await db_session.flush()

    asc = await authed_client.get("/api/v1/incidents?sort_by=resolved_at&sort_dir=asc")
    assert asc.status_code == 200
    assert [r["id"] for r in asc.json()] == [b.id, c.id, a.id]

    desc = await authed_client.get("/api/v1/incidents?sort_by=resolved_at&sort_dir=desc")
    assert desc.status_code == 200
    assert [r["id"] for r in desc.json()] == [a.id, c.id, b.id]


@pytest.mark.asyncio
async def test_list_incidents_unknown_sort_by_is_422(authed_client: AsyncClient):
    resp = await authed_client.get("/api/v1/incidents?sort_by=nonexistent")
    assert resp.status_code == 422
