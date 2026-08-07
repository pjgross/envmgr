"""release.owning_project_id — the link, and the IDOR surface it adds.

Named owning_project_id, not project_id: `release_kind='project'` already lives
on this table meaning "not an enterprise release", and two things called
project on one row is how a future reader gets it wrong.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.base import get_db
from app.db.models.release import Release
from app.main import app
from tests.factories import ensure_project


@pytest_asyncio.fixture(scope="function")
async def authed_client(db_session, tenant, user) -> AsyncClient:
    """Copied from tests/integration/test_release_systems_api.py — every
    release test in this repo builds its client this way, over the `tenant`
    and `user` fixtures rather than `test_tenant`/`test_user`."""
    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/api/v1/auth/login", json={
            "username": user.username, "password": "password123",
            "tenant_slug": tenant.slug,
        })
        assert resp.status_code == 200, resp.text
        ac.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
        yield ac
    app.dependency_overrides.clear()


def _payload(lifecycle_template_id: int, **extra) -> dict:
    body = {
        "name": "Rel",
        "release_type": "Test Major",
        "release_kind": "project",
        "lifecycle_template_id": lifecycle_template_id,
    }
    body.update(extra)
    return body


@pytest.mark.asyncio
async def test_the_owning_projects_name_travels_with_the_release(
    authed_client, db_session, tenant, release_lifecycle_template
):
    project = await ensure_project(db_session, tenant.id, name="Mortgage")
    await db_session.commit()

    created = await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=project.id),
    )
    assert created.status_code == 201, created.text
    assert created.json()["owning_project_id"] == project.id
    assert created.json()["owning_project_name"] == "Mortgage"
    # release_kind is a different concept and stays untouched.
    assert created.json()["release_kind"] == "project"


@pytest.mark.asyncio
async def test_a_release_without_an_owning_project_is_still_valid(
    authed_client, release_lifecycle_template
):
    created = await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )
    assert created.status_code == 201, created.text
    assert created.json()["owning_project_id"] is None
    assert created.json()["owning_project_name"] is None


@pytest.mark.asyncio
async def test_cannot_own_a_release_with_another_tenants_project_on_create(
    authed_client, db_session, release_lifecycle_template, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=theirs.id),
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_cannot_own_a_release_with_another_tenants_project_on_update(
    authed_client, db_session, release_lifecycle_template, second_tenant_factory
):
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )).json()["id"]

    # NOTE: release update is PUT /releases/{id}, not PATCH — see
    # app/api/v1/releases.py's @router.put("/{release_id}").
    refused = await authed_client.put(
        f"/api/v1/releases/{rid}", json={"owning_project_id": theirs.id}
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_release_list_filters_by_project_in_sql(
    authed_client, db_session, tenant, release_lifecycle_template
):
    mortgage = await ensure_project(db_session, tenant.id, name="Mortgage")
    savings = await ensure_project(db_session, tenant.id, name="Savings")
    await db_session.commit()

    for index, project in enumerate((mortgage, savings)):
        made = await authed_client.post(
            "/api/v1/releases",
            json=_payload(
                release_lifecycle_template.id,
                name=f"Rel {index}",
                owning_project_id=project.id,
            ),
        )
        assert made.status_code == 201, made.text

    filtered = await authed_client.get(f"/api/v1/releases?project_id={mortgage.id}")
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()
    assert len(rows) == 1
    assert rows[0]["owning_project_name"] == "Mortgage"
    assert int(filtered.headers["X-Total-Count"]) == 1


# ── Finding 1: resubmitting the release's OWN archived project must not 404 ─


@pytest.mark.asyncio
async def test_resubmitting_the_same_archived_project_on_update_succeeds(
    authed_client, db_session, tenant, release_lifecycle_template
):
    """A full-form PUT resubmitting the release's own project id — now
    archived — while changing an unrelated field must not 404. Reproduced
    against the unfixed code: project_service.get_project filters
    deleted_at IS NULL, so this 404'd even though the project link itself
    was not changing. ReleaseForm.tsx sends a fixed whitelist payload on
    every save, so this is what Task 5 makes reachable in the UI."""
    project = await ensure_project(db_session, tenant.id, name="Archived Later")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=project.id),
    )).json()["id"]

    archived = await authed_client.delete(f"/api/v1/projects/{project.id}")
    assert archived.status_code == 204, archived.text

    saved = await authed_client.put(
        f"/api/v1/releases/{rid}",
        json={
            "name": "Rel renamed",
            "release_type": "Test Major",
            "owning_project_id": project.id,
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["name"] == "Rel renamed"
    assert body["owning_project_id"] == project.id
    assert body["owning_project_name"] == "Archived Later"


@pytest.mark.asyncio
async def test_assigning_a_different_archived_project_on_update_still_404s(
    authed_client, db_session, tenant, release_lifecycle_template
):
    """The exemption is narrow: it only covers resubmitting the CURRENT
    value. A NEW assignment to a different archived project must still 404."""
    original = await ensure_project(db_session, tenant.id, name="Original")
    other = await ensure_project(db_session, tenant.id, name="Also Archived")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=original.id),
    )).json()["id"]

    archived = await authed_client.delete(f"/api/v1/projects/{other.id}")
    assert archived.status_code == 204, archived.text

    refused = await authed_client.put(
        f"/api/v1/releases/{rid}",
        json={
            "name": "Rel",
            "release_type": "Test Major",
            "owning_project_id": other.id,
        },
    )
    assert refused.status_code == 404, refused.text


# ── Finding 2: the update path's happy case was never asserted at all ───────


@pytest.mark.asyncio
async def test_the_owning_project_link_persists_after_update(
    authed_client, db_session, tenant, release_lifecycle_template
):
    """PUT the link onto a release that had none, assert the response
    carries both the id and the resolved name, then re-GET and confirm it
    stuck."""
    project = await ensure_project(db_session, tenant.id, name="Newly Linked")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )).json()["id"]

    saved = await authed_client.put(
        f"/api/v1/releases/{rid}",
        json={
            "name": "Rel",
            "release_type": "Test Major",
            "owning_project_id": project.id,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["owning_project_id"] == project.id
    assert saved.json()["owning_project_name"] == "Newly Linked"

    reget = await authed_client.get(f"/api/v1/releases/{rid}")
    assert reget.status_code == 200, reget.text
    assert reget.json()["owning_project_id"] == project.id
    assert reget.json()["owning_project_name"] == "Newly Linked"


# ── Finding 3: owning_project_name was unguarded on GET, PUT and /transition ─


@pytest.mark.asyncio
async def test_get_after_create_carries_the_owning_project_name(
    authed_client, db_session, tenant, release_lifecycle_template
):
    """create_release's response was the only place this was exercised.
    Re-GET the same release and confirm the name is still there — this is
    what actually exercises _release_with_permissions's lookup."""
    project = await ensure_project(db_session, tenant.id, name="Re-GET Me")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases",
        json=_payload(release_lifecycle_template.id, owning_project_id=project.id),
    )).json()["id"]

    reget = await authed_client.get(f"/api/v1/releases/{rid}")
    assert reget.status_code == 200, reget.text
    assert reget.json()["owning_project_id"] == project.id
    assert reget.json()["owning_project_name"] == "Re-GET Me"


# ── Finding 5: get_project_names' own tenant filter, unreachable via the API ─


@pytest.mark.asyncio
async def test_a_malformed_cross_tenant_project_row_does_not_leak_its_name(
    authed_client, db_session, tenant, release_lifecycle_template, second_tenant_factory
):
    """No write path can produce this row — both create and update refuse a
    cross-tenant project id. This guards get_project_names' own tenant
    filter directly, in case that write-side defence is ever the only thing
    standing between a malformed row and a name leak."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Not Ours")
    await db_session.commit()
    rid = (await authed_client.post(
        "/api/v1/releases", json=_payload(release_lifecycle_template.id)
    )).json()["id"]

    release = (
        await db_session.execute(select(Release).where(Release.id == rid))
    ).scalar_one()
    release.owning_project_id = theirs.id
    await db_session.commit()

    fetched = await authed_client.get(f"/api/v1/releases/{rid}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["owning_project_name"] is None
