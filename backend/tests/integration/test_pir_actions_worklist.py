"""GET /pir-actions — the page that makes a PIR action a thing someone does.

Actions that live only inside the release tab they were raised in are exactly
the ones nobody does, so every filter here runs in SQL, before the window, and
X-Total-Count describes the FILTERED set.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.pir import PIR
from app.db.models.release import Release
from app.services.incident_defaults import seed_incident_defaults_for_tenant


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Authenticated HTTP client scoped to `tenant`/`user`."""
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
    tpl = LifecycleTemplate(
        tenant_id=tenant.id,
        entity_type="release",
        name="PIR Worklist Test Major",
        is_default=True,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "completed", "label": "Completed", "is_initial": False,
                 "is_terminal": True},
            ],
            "transitions": [],
            "field_permissions": {},
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant.id,
        name="PIR Integration Test Release",
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


async def _pir(db, tenant_id, user_id, name="R"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"RT-{name}", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl)
    await db.flush()
    r = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(r)
    await db.flush()
    p = PIR(tenant_id=tenant_id, release_id=r.id, summary=None, status="draft", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


async def _pir_with_action(client, release_id, *, title, **action):
    await client.post(f"/api/v1/releases/{release_id}/pir", json={"summary": "s"})
    fid = (await client.post(f"/api/v1/releases/{release_id}/pir/findings",
                             json={"kind": "went_wrong", "title": "F"})).json()["id"]
    resp = await client.post(f"/api/v1/releases/{release_id}/pir/findings/{fid}/actions",
                             json={"title": title, **action})
    assert resp.status_code == 201, resp.text
    return fid, resp.json()["id"]


@pytest.mark.asyncio
async def test_rows_name_the_release_and_the_finding_not_their_ids(authed_client,
                                                                   demo_release_id):
    await _pir_with_action(authed_client, demo_release_id, title="Add a perf gate")
    resp = await authed_client.get("/api/v1/pir-actions")
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["title"] == "Add a perf gate"
    assert row["release_name"] == "PIR Integration Test Release"
    assert row["finding_title"] == "F"
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_status_filter_runs_in_sql_and_the_total_follows_it(authed_client,
                                                                  demo_release_id):
    fid, aid = await _pir_with_action(authed_client, demo_release_id, title="A")
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
                             json={"title": "B", "status": "done"})
    resp = await authed_client.get("/api/v1/pir-actions?status=open")
    assert [r["title"] for r in resp.json()] == ["A"]
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_no_selection_is_an_omitted_key_not_the_word_all(authed_client, demo_release_id):
    """`all` is buildParams' own sentinel; a vocabulary containing it builds
    byte-identical params for two different states. Four sub-projects have hit
    this. An explicit empty value is a 422, not a silently ignored filter."""
    await _pir_with_action(authed_client, demo_release_id, title="A")
    assert len((await authed_client.get("/api/v1/pir-actions")).json()) == 1
    assert (await authed_client.get("/api/v1/pir-actions?status=")).status_code == 422
    assert (await authed_client.get("/api/v1/pir-actions?status=all")).status_code == 422


@pytest.mark.asyncio
async def test_overdue_filter_uses_the_whole_due_day(authed_client, demo_release_id):
    """Due today is not overdue. The filter and the rendered flag come from one
    clock per request, so a row cannot be selected as overdue and render as not."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fid, _ = await _pir_with_action(
        authed_client, demo_release_id, title="due today",
        due_date=today.isoformat().replace("+00:00", "Z"))
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "due yesterday",
              "due_date": (today - timedelta(days=1)).isoformat().replace("+00:00", "Z")})
    resp = await authed_client.get("/api/v1/pir-actions?overdue=true")
    assert [r["title"] for r in resp.json()] == ["due yesterday"]
    assert resp.json()[0]["is_overdue"] is True


@pytest.mark.asyncio
async def test_overdue_false_is_the_exact_complement(authed_client, demo_release_id):
    """True and false must PARTITION the worklist. An undated action, and one
    that is closed past its date, belong to exactly one of the two answers —
    otherwise a user filtering both ways never sees them at all."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = (today - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    fid, _ = await _pir_with_action(authed_client, demo_release_id, title="undated")
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "due today", "due_date": today.isoformat().replace("+00:00", "Z")})
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "late", "due_date": yesterday})
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "late but done", "due_date": yesterday, "status": "done"})

    overdue = {r["title"] for r in (
        await authed_client.get("/api/v1/pir-actions?overdue=true")).json()}
    not_overdue = {r["title"] for r in (
        await authed_client.get("/api/v1/pir-actions?overdue=false")).json()}
    everything = {r["title"] for r in (await authed_client.get("/api/v1/pir-actions")).json()}
    assert overdue == {"late"}
    assert overdue | not_overdue == everything
    assert overdue & not_overdue == set()


@pytest.mark.asyncio
async def test_a_done_action_past_its_date_is_not_overdue(authed_client, demo_release_id):
    fid, aid = await _pir_with_action(
        authed_client, demo_release_id, title="A", due_date="2020-01-01T00:00:00Z")
    await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}",
        json={"status": "done"})
    assert (await authed_client.get("/api/v1/pir-actions?overdue=true")).json() == []


@pytest.mark.asyncio
async def test_incident_filter_answers_what_is_being_done_about_this_incident(authed_client,
                                                                             demo_release_id,
                                                                             db_session, tenant):
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()
    fid, _ = await _pir_with_action(authed_client, demo_release_id, title="Add a perf gate")
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": inc.id})
    resp = await authed_client.get(f"/api/v1/pir-actions?incident_id={inc.id}")
    assert [r["title"] for r in resp.json()] == ["Add a perf gate"]
    assert (await authed_client.get(
        f"/api/v1/pir-actions?incident_id={inc.id + 999}")).json() == []


@pytest.mark.asyncio
async def test_the_owner_filter_narrows_to_one_persons_work(authed_client, demo_release_id, user):
    """"What do I owe" is the question this worklist exists to answer, so the
    owner filter runs in SQL like every other and the total follows it."""
    fid, _ = await _pir_with_action(authed_client, demo_release_id, title="mine",
                                    owner_id=user.id)
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
                             json={"title": "nobody's"})
    resp = await authed_client.get(f"/api/v1/pir-actions?owner_id={user.id}")
    assert [r["title"] for r in resp.json()] == ["mine"]
    assert resp.json()[0]["owner_username"] == user.username
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_the_release_filter_narrows_to_one_reviews_work(authed_client, demo_release_id,
                                                              db_session, tenant, user):
    """The same worklist, scoped back down to one release — what the release
    page's own tab shows. Both must agree, so it is the same query with a
    filter, not a second one."""
    other = await _pir(db_session, tenant.id, user.id, name="Other Release")
    await db_session.commit()
    await _pir_with_action(authed_client, demo_release_id, title="mine")
    await _pir_with_action(authed_client, other.release_id, title="theirs")

    resp = await authed_client.get(f"/api/v1/pir-actions?release_id={demo_release_id}")
    assert [r["title"] for r in resp.json()] == ["mine"]
    assert resp.headers["X-Total-Count"] == "1"
    assert len((await authed_client.get("/api/v1/pir-actions")).json()) == 2


@pytest.mark.asyncio
async def test_the_incident_filter_selects_only_the_findings_that_cite_it(authed_client,
                                                                          demo_release_id,
                                                                          db_session, tenant):
    """The EXISTS must correlate on the finding, not merely on the incident.
    Uncorrelated, "somebody cited this incident" is true for the whole tenant,
    so the filter answers with every action in the estate while looking right on
    a fixture where only one finding exists.
    """
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()

    cited_fid, _ = await _pir_with_action(authed_client, demo_release_id, title="cited")
    other_fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "unrelated"})).json()["id"]
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{other_fid}/actions",
        json={"title": "unrelated action"})
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{cited_fid}/incidents",
        json={"incident_id": inc.id})

    resp = await authed_client.get(f"/api/v1/pir-actions?incident_id={inc.id}")
    assert [r["title"] for r in resp.json()] == ["cited"]
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_an_unknown_sort_by_is_a_422_not_a_silent_fallback(authed_client, demo_release_id):
    await _pir_with_action(authed_client, demo_release_id, title="A")
    assert (await authed_client.get("/api/v1/pir-actions?sort_by=owner_id")).status_code == 422


@pytest.mark.asyncio
async def test_an_unowned_action_survives_sorting_by_owner(authed_client, demo_release_id):
    """The owner join must be an OUTER join: an inner one drops every action
    nobody has picked up yet — precisely the rows a worklist exists to show —
    and only when someone clicks the column header."""
    await _pir_with_action(authed_client, demo_release_id, title="Nobody's")
    resp = await authed_client.get("/api/v1/pir-actions?sort_by=owner")
    assert resp.status_code == 200, resp.text
    assert [r["title"] for r in resp.json()] == ["Nobody's"]
    assert resp.headers["X-Total-Count"] == "1"


def test_the_worklist_order_by_ends_in_a_unique_key():
    """The plan expected the paging test below to catch a missing tiebreaker on
    PostgreSQL. It does not: dropping `.order_by(PirAction.id)` leaves all
    twelve tests green on BOTH engines, because six rows in a fresh table come
    back in physical order every time. So the clause itself is the only thing
    left to assert, through the exposed query builder — the same documented
    exception `environment_health_service.history_query` carries. Asserting the
    service's OWN query, never one rebuilt here, which would only prove the test
    wrote a tiebreaker.
    """
    from datetime import datetime, timezone
    from app.core.pagination import Sort
    from app.db.models.pir_finding import PirAction
    from app.services import pir_finding_service

    for sort in (None, Sort(column=PirAction.due_date, descending=False)):
        compiled = str(pir_finding_service.worklist_query(
            1, now=datetime(2026, 8, 30, tzinfo=timezone.utc), sort=sort))
        assert "ORDER BY" in compiled, "the worklist must be ordered at all"
        # The tail after the LAST "ORDER BY" — the SELECT list mentions
        # pir_action.id too, so splitting on the keyword is the whole point.
        order_by = compiled.rsplit("ORDER BY", 1)[1]
        assert order_by.strip().endswith("pir_action.id"), \
            "the ORDER BY must END in a unique key"


@pytest.mark.asyncio
async def test_paging_neither_duplicates_nor_drops_a_row_when_due_dates_tie(authed_client,
                                                                            demo_release_id):
    """Every action here shares one due date. The id tiebreaker is what makes
    this deterministic; note it is the structural test above that guards it —
    this one stays green either way (see that test's docstring)."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings",
                                    json={"kind": "went_wrong", "title": "F"})).json()["id"]
    for n in range(6):
        await authed_client.post(
            f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
            json={"title": f"A{n}", "due_date": "2026-09-30T00:00:00Z"})
    seen = []
    for offset in (0, 2, 4):
        page = await authed_client.get(f"/api/v1/pir-actions?limit=2&offset={offset}")
        seen.extend(r["id"] for r in page.json())
    assert len(seen) == 6
    assert len(set(seen)) == 6


@pytest.mark.asyncio
async def test_another_tenants_actions_are_not_in_my_worklist(authed_client, demo_release_id,
                                                              db_session, tenant, user):
    """Mutation check: drop the tenant filter from list_actions and this fails."""
    from app.api.v1.schemas.pir_finding import PirActionCreate, PirFindingCreate
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash
    from app.services import pir_finding_service
    other = Tenant(name="Other Org WL", slug="other-org-wl")
    db_session.add(other)
    await db_session.flush()
    stranger = User(tenant_id=other.id, username="stranger-wl", email="s@wl.test",
                    password_hash=get_password_hash("password123"), role="Developer",
                    is_active=True)
    db_session.add(stranger)
    await db_session.flush()
    theirs_pir = await _pir(db_session, other.id, stranger.id, name="Theirs")
    theirs_finding = await pir_finding_service.create_finding(
        db_session, other.id, theirs_pir, PirFindingCreate(kind="went_wrong", title="T"),
        stranger.id)
    await pir_finding_service.create_action(
        db_session, other.id, theirs_finding, PirActionCreate(title="Not mine"), stranger.id)
    await db_session.flush()

    await _pir_with_action(authed_client, demo_release_id, title="Mine")
    titles = [r["title"] for r in (await authed_client.get("/api/v1/pir-actions")).json()]
    assert titles == ["Mine"]


@pytest.mark.asyncio
async def test_a_deleted_action_leaves_the_worklist(authed_client, demo_release_id):
    """Deleting the action itself is the commonest of the three withdrawals and
    the one a filter on the join alone would miss entirely."""
    fid, aid = await _pir_with_action(authed_client, demo_release_id, title="A")
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
                             json={"title": "B"})
    await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}")
    resp = await authed_client.get("/api/v1/pir-actions")
    assert [r["title"] for r in resp.json()] == ["B"]
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_a_deleted_pir_takes_its_actions_off_the_worklist(authed_client, demo_release_id):
    """Withdrawing the whole review withdraws its work. The finding and action
    rows survive a soft-deleted PIR untouched, so only the PIR-side filter
    catches this one."""
    await _pir_with_action(authed_client, demo_release_id, title="A")
    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir")).status_code == 204
    resp = await authed_client.get("/api/v1/pir-actions")
    assert resp.json() == []
    assert resp.headers["X-Total-Count"] == "0"


@pytest.mark.asyncio
async def test_a_deleted_finding_takes_its_actions_off_the_worklist(authed_client,
                                                                    demo_release_id):
    """The worklist joins through the finding and the PIR, so withdrawing either
    must remove the work — an action nobody can reach from the release page is
    not work anybody can do."""
    fid, _ = await _pir_with_action(authed_client, demo_release_id, title="A")
    await authed_client.delete(f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}")
    resp = await authed_client.get("/api/v1/pir-actions")
    assert resp.json() == []
    assert resp.headers["X-Total-Count"] == "0"
