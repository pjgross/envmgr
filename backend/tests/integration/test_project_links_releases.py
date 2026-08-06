"""release.owning_project_id — the link, and the IDOR surface it adds.

Named owning_project_id, not project_id: `release_kind='project'` already lives
on this table meaning "not an enterprise release", and two things called
project on one row is how a future reader gets it wrong.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.base import get_db
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
