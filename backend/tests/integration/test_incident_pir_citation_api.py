"""POST /incidents/{id}/pir-citation — the journey this feature exists for.

Choose a release that has gone live, then either cite an existing finding or
create one. If that release has no PIR yet, it is created as part of the
citation. Nothing here prompts creating a RELEASE, and nothing asks for a fix
release — the dead end this replaces.
"""
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.incident import Incident
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.user import Tenant, User
from app.core.security import get_password_hash
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
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


async def _release(db_session, tenant_id, raised_by, name) -> int:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"RT-{name}", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=raised_by)
    db_session.add(r)
    await db_session.flush()
    return r.id


@pytest_asyncio.fixture
async def demo_release_id(db_session, tenant, user) -> int:
    rid = await _release(db_session, tenant.id, user.id, "Citation Test Release")
    await db_session.commit()
    return rid


@pytest_asyncio.fixture
async def other_release_id(db_session, tenant, user) -> int:
    rid = await _release(db_session, tenant.id, user.id, "Other Citation Release")
    await db_session.commit()
    return rid


@pytest_asyncio.fixture
async def foreign_release_id(db_session) -> int:
    """A release in a DIFFERENT tenant — reachable by id, and only by id."""
    other = Tenant(name="Other Org Citation", slug="other-org-citation")
    db_session.add(other)
    await db_session.flush()
    stranger = User(tenant_id=other.id, username="stranger-citation",
                    email="stranger@citation.test",
                    password_hash=get_password_hash("password123"), role="Admin", is_active=True)
    db_session.add(stranger)
    await db_session.flush()
    rid = await _release(db_session, other.id, stranger.id, "Foreign Release")
    await db_session.commit()
    return rid


@pytest_asyncio.fixture
async def incident(db_session, tenant) -> Incident:
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()
    await db_session.commit()
    return inc


@pytest.mark.asyncio
async def test_citing_creates_the_pir_the_finding_and_the_action_in_one_call(authed_client,
                                                                            demo_release_id,
                                                                            incident):
    """One transaction. `get_db` commits per request, so three separate calls
    would leave a PIR behind with no citation on it when the second failed."""
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={
            "release_id": demo_release_id,
            "new_finding": {
                "title": "No load test before go-live",
                "detail": "Perf suite is opt-in",
                "root_cause": "The perf gate is optional on this template",
                "actions": [{"title": "Make the perf gate mandatory for Tier 1"}],
            },
            "note": "root incident",
        },
    )
    assert resp.status_code == 201, resp.text
    citations = resp.json()
    assert len(citations) == 1
    assert citations[0]["finding_title"] == "No load test before go-live"
    assert citations[0]["open_action_count"] == 1
    assert citations[0]["note"] == "root incident"
    assert citations[0]["root_cause"] == "The perf gate is optional on this template"

    pir = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert pir is not None
    assert pir["findings"][0]["incidents"][0]["incident_id"] == incident.id
    assert pir["findings"][0]["kind"] == "went_wrong"
    assert pir["findings"][0]["actions"][0]["title"] == "Make the perf gate mandatory for Tier 1"


@pytest.mark.asyncio
async def test_citing_an_existing_finding_adds_no_second_pir(authed_client, demo_release_id,
                                                             incident):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "Existing"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 201
    assert resp.json()[0]["finding_id"] == fid
    # Still ONE review on that release, and one finding on it.
    pir = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert len(pir["findings"]) == 1


@pytest.mark.asyncio
async def test_both_or_neither_is_a_422(authed_client, demo_release_id, incident):
    both = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": 1,
              "new_finding": {"title": "T"}})
    assert both.status_code == 422
    neither = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id})
    assert neither.status_code == 422


@pytest.mark.asyncio
async def test_a_refused_request_leaves_no_pir_behind(authed_client, demo_release_id, incident):
    """The reason this is one endpoint rather than three calls: a request that
    fails after the PIR would have been created must leave the release with no
    review at all, not an empty one nobody asked for."""
    assert (await authed_client.get(
        f"/api/v1/releases/{demo_release_id}/pir")).json() is None
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": 999999})
    assert resp.status_code in (404, 422)
    assert (await authed_client.get(
        f"/api/v1/releases/{demo_release_id}/pir")).json() is None


@pytest.mark.asyncio
async def test_a_release_with_no_recorded_actual_date_is_still_citable(authed_client,
                                                                      demo_release_id, incident):
    """`implemented` is a PICKER FILTER, a helper for choosing well — not a rule
    about what a PIR may be attached to. A release whose actual date nobody
    recorded must not become unreviewable."""
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "new_finding": {"title": "T"}})
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_a_finding_belonging_to_another_release_is_a_422(authed_client, demo_release_id,
                                                               other_release_id, incident):
    """A finding id from a different release must not silently attach the citation
    to the wrong review.

    THE TARGET RELEASE HAS ITS OWN PIR, deliberately: without one the endpoint
    refuses earlier, for a different reason ("a finding cannot belong to a PIR
    that does not exist"), and the containment check itself is never reached —
    which is how a tenant-only lookup passed this test in an earlier draft.
    """
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "mine"})
    await authed_client.post(f"/api/v1/releases/{other_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{other_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "Elsewhere"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_citing_a_went_well_finding_is_refused(authed_client, demo_release_id, incident):
    """An incident is evidence that something went WRONG. Citing it against a
    'keep doing this' item would put a production failure in the good column."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_well", "title": "Canary caught it"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_a_404(authed_client, incident, foreign_release_id):
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": foreign_release_id, "new_finding": {"title": "T"}})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_an_incident_in_another_tenant_is_a_404(authed_client, demo_release_id, db_session):
    """The incident id in the path is checked too — it is the other half of the
    pair, and a citation raised against someone else's incident would be
    invisible to them and wrong for us."""
    other = Tenant(name="Other Org Citation Inc", slug="other-org-citation-inc")
    db_session.add(other)
    await db_session.flush()
    theirs = Incident(tenant_id=other.id, title="Theirs", severity="P2", status="open",
                      detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(theirs)
    await db_session.flush()
    await db_session.commit()
    resp = await authed_client.post(
        f"/api/v1/incidents/{theirs.id}/pir-citation",
        json={"release_id": demo_release_id, "new_finding": {"title": "T"}})
    assert resp.status_code == 404


@pytest_asyncio.fixture(scope="function")
async def realistic_authed_client(db_engine, db_session, tenant, user) -> AsyncClient:
    """An authenticated client whose `get_db` override mirrors production —
    commit on success, ROLLBACK on exception, a fresh session per request.

    The ordinary `authed_client` shares one session with the test body and never
    rolls back, so it cannot see a write that only the real transaction boundary
    discards. Modelled on conftest's `realistic_client`, which carries no auth;
    this one logs in, and does not request that fixture, because both assign
    into the same global `app.dependency_overrides[get_db]`.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _Session

    await seed_incident_defaults_for_tenant(db_session, tenant.id)
    await db_session.commit()

    Session = async_sessionmaker(db_engine, class_=_Session, expire_on_commit=False)

    async def override_get_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

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
async def test_a_refusal_partway_through_leaves_nothing_behind(realistic_authed_client,
                                                               demo_release_id, incident):
    """The whole reason this is ONE endpoint rather than three calls.

    An action naming a user from another tenant is refused AFTER the PIR and the
    finding have been inserted, so only the real transaction boundary can undo
    them — which is why this test uses a production-shaped session rather than
    the shared one. Three separate calls from the dialog could not be undone at
    all: `get_db` commits per request, so the PIR would simply stay.
    """
    client = realistic_authed_client
    assert (await client.get(f"/api/v1/releases/{demo_release_id}/pir")).json() is None

    resp = await client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id,
              "new_finding": {"title": "T", "actions": [{"title": "A", "owner_id": 999999}]}})
    assert resp.status_code == 422, resp.text

    # No PIR, no finding, no citation — the release is exactly as it was.
    assert (await client.get(f"/api/v1/releases/{demo_release_id}/pir")).json() is None
    assert (await client.get(f"/api/v1/incidents/{incident.id}")).json()["pir_citations"] == []
