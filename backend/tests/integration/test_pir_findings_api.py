"""Integration tests for the PIR findings API — Task 2."""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`."""
    # Seed incident defaults so that PIR tests linked to incidents work.
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


@pytest_asyncio.fixture(scope="function")
async def demo_release_id(db_session, tenant, user) -> int:
    """A persisted Release in the test tenant; yields its id."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="PIR Findings Test Major",
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
        name="PIR Findings Integration Test Release",
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
async def test_findings_come_back_on_the_pir(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    created = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test", "root_cause": "Perf gate optional"},
    )
    assert created.status_code == 201, created.text

    got = await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")
    body = got.json()
    assert [f["title"] for f in body["findings"]] == ["No load test"]
    assert body["findings"][0]["root_cause"] == "Perf gate optional"
    assert body["findings"][0]["seq"] == 1


@pytest.mark.asyncio
async def test_a_finding_on_a_release_with_no_pir_is_a_404(authed_client, demo_release_id):
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_422(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_sideways", "title": "T"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_dropped(authed_client, demo_release_id):
    """extra='forbid'. FastAPI and Pydantic drop unknown keys silently, and this
    codebase has shipped that bug three times."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T", "rootcause": "typo"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_and_delete_a_finding(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_well", "title": "Canary caught it"},
    )).json()["id"]

    patched = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}", json={"detail": "ran 30 min"})
    assert patched.status_code == 200
    assert patched.json()["title"] == "Canary caught it"
    assert patched.json()["detail"] == "ran 30 min"

    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}")).status_code == 204
    assert (await authed_client.get(
        f"/api/v1/releases/{demo_release_id}/pir")).json()["findings"] == []


@pytest.mark.asyncio
async def test_an_action_round_trips_on_the_pir_read(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test"})).json()["id"]
    created = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "Add a perf gate", "due_date": "2026-09-30T00:00:00Z"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "open"
    assert created.json()["is_overdue"] is False

    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert [a["title"] for a in body["findings"][0]["actions"]] == ["Add a perf gate"]


@pytest.mark.asyncio
async def test_closing_an_action_names_when_it_closed(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    aid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "T"})).json()["id"]
    resp = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}",
        json={"status": "done", "closure_note": "gate added"})
    assert resp.status_code == 200
    assert resp.json()["closed_at"] is not None
    assert resp.json()["closure_note"] == "gate added"


@pytest.mark.asyncio
async def test_an_owner_from_another_tenant_is_a_422(authed_client, demo_release_id, db_session):
    """The FK validation, proved by pointing at a user id that exists but is not
    ours — not at an id nobody has."""
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash
    other = Tenant(name="Other Org PIR", slug="other-org-pir")
    db_session.add(other)
    await db_session.flush()
    stranger = User(tenant_id=other.id, username="stranger-pir", email="s@x.test",
                    password_hash=get_password_hash("password123"), role="Developer")
    db_session.add(stranger)
    await db_session.flush()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "T", "owner_id": stranger.id})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_action_status_is_a_422_on_the_route(authed_client, demo_release_id):
    """Companion to the schema-level
    test_an_unknown_status_is_refused_by_the_schema in
    test_pir_action_service.py: that one pins the ValueError at construction,
    this one pins the HTTP contract an API caller actually sees."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    aid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "T"})).json()["id"]
    resp = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}",
        json={"status": "nearly"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_finding_from_another_release_pir_is_a_422_on_this_release(
    authed_client, demo_release_id, db_session, tenant, user
):
    """The release_id in the URL must not be decorative: a finding id that is
    real, and in the caller's own tenant, but belongs to a DIFFERENT release's
    PIR is refused rather than silently read or mutated."""
    tpl = LifecycleTemplate(
        tenant_id=tenant.id, entity_type="release", name="PIR X-PIR Test",
        is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    other_release = Release(
        tenant_id=tenant.id, name="Other Release", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user.id,
    )
    db_session.add(other_release)
    await db_session.flush()
    await db_session.commit()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    await authed_client.post(f"/api/v1/releases/{other_release.id}/pir", json={"summary": "s2"})
    other_fid = (await authed_client.post(
        f"/api/v1/releases/{other_release.id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]

    patch_resp = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{other_fid}", json={"detail": "x"})
    assert patch_resp.status_code == 422

    delete_resp = await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{other_fid}")
    assert delete_resp.status_code == 422


@pytest.mark.asyncio
async def test_an_action_from_another_finding_is_a_422_on_this_finding(
    authed_client, demo_release_id
):
    """The finding_id in the URL must not be decorative either: an action id
    that is real, and on the same PIR, but hangs off a DIFFERENT finding is
    refused rather than silently read or mutated."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid_a = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "A"})).json()["id"]
    fid_b = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "B"})).json()["id"]
    action_b = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid_b}/actions",
        json={"title": "T"})).json()["id"]

    patch_resp = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid_a}/actions/{action_b}",
        json={"status": "done"})
    assert patch_resp.status_code == 422

    delete_resp = await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid_a}/actions/{action_b}")
    assert delete_resp.status_code == 422


@pytest.mark.asyncio
async def test_citing_an_incident_shows_it_on_the_finding_by_name(authed_client, demo_release_id,
                                                                  db_session, tenant):
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": inc.id, "note": "root incident"})
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["incident_title"] == "Checkout 500s"

    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert body["findings"][0]["incidents"][0]["severity"] == "P1"

    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents/{inc.id}"
    )).status_code == 204
    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert body["findings"][0]["incidents"] == []


@pytest.mark.asyncio
async def test_citing_through_another_releases_path_is_a_422(
    authed_client, demo_release_id, db_session, tenant, user
):
    """The containment rule the finding and action routes already follow, on the
    citation routes too: a real finding id reached through the wrong release's
    path is refused, not silently cited."""
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    tpl = LifecycleTemplate(
        tenant_id=tenant.id, entity_type="release", name="PIR Citation Other Release",
        is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    other_release = Release(
        tenant_id=tenant.id, name="Other Citation Release", release_type="Major",
        release_kind="project", lifecycle_template_id=tpl.id, status="draft", raised_by=user.id,
    )
    db_session.add(other_release)
    await db_session.flush()
    await db_session.commit()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    await authed_client.post(f"/api/v1/releases/{other_release.id}/pir", json={"summary": "s2"})
    other_fid = (await authed_client.post(
        f"/api/v1/releases/{other_release.id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]

    post_resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{other_fid}/incidents",
        json={"incident_id": inc.id})
    assert post_resp.status_code == 422

    delete_resp = await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{other_fid}/incidents/{inc.id}")
    assert delete_resp.status_code == 422


@pytest.mark.asyncio
async def test_an_incident_from_another_tenant_is_a_422_on_the_route(
    authed_client, demo_release_id, db_session
):
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    from app.db.models.user import Tenant
    other = Tenant(name="Other Org PIR Citation API", slug="other-org-pir-citation-api")
    db_session.add(other)
    await db_session.flush()
    theirs = Incident(tenant_id=other.id, title="Theirs", severity="P2", status="open",
                      detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(theirs)
    await db_session.flush()
    await db_session.commit()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": theirs.id})
    assert resp.status_code == 422
