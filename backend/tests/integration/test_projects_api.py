"""Project CRUD. Usage agreements and the entity links have their own files."""
import pytest

from app.core.pagination import TOTAL_COUNT_HEADER
from tests.factories import ensure_project, ensure_user_group


@pytest.mark.asyncio
async def test_create_and_list_a_project(client, auth_headers):
    created = await client.post(
        "/api/v1/projects",
        json={"name": "Mortgage Replatform", "code": "MTG", "description": "2026 programme"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Mortgage Replatform"
    assert created.json()["is_active"] is True

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert [p["name"] for p in listed.json()] == ["Mortgage Replatform"]
    assert int(listed.headers[TOTAL_COUNT_HEADER]) == 1


@pytest.mark.asyncio
async def test_duplicate_name_is_a_409_naming_the_conflict(client, auth_headers):
    await client.post("/api/v1/projects", json={"name": "Mortgage"}, headers=auth_headers)
    again = await client.post(
        "/api/v1/projects", json={"name": "mortgage"}, headers=auth_headers
    )
    assert again.status_code == 409, again.text
    assert "already exists" in again.json()["detail"].lower()


@pytest.mark.asyncio
async def test_the_team_name_travels_with_the_row(
    client, auth_headers, db_session, test_tenant
):
    """Resolving it in the browser against a capped groups collection is the
    `.find()` failure docs/pagination.md documents — a miss renders '—'."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Mortgage Team")
    await db_session.commit()

    created = await client.post(
        "/api/v1/projects",
        json={"name": "Mortgage", "team_group_id": group.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["team_group_name"] == "Mortgage Team"


@pytest.mark.asyncio
async def test_cannot_point_at_another_tenants_group(
    client, auth_headers, db_session, second_tenant_factory
):
    """404, never 403 — a 403 confirms the group exists."""
    # The fixture yields a FACTORY, and the factory returns (Tenant, User).
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    refused = await client.post(
        "/api/v1/projects",
        json={"name": "Leaky", "team_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_the_update_path_guards_the_team_too(
    client, auth_headers, db_session, second_tenant_factory
):
    """The create path is the obvious one; the UPDATE path is where this gap
    has hidden before — a prior sub-project's review found exactly that."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_user_group(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()
    pid = (await client.post(
        "/api/v1/projects", json={"name": "Mine"}, headers=auth_headers
    )).json()["id"]

    refused = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"team_group_id": theirs.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


@pytest.mark.asyncio
async def test_delete_is_a_soft_delete_and_is_never_refused(
    client, auth_headers, db_session, test_tenant
):
    """Deliberately unlike delete_group, which 409s while anything references
    it. A project accumulates every booking it ever had, so a reference check
    would make every project permanently undeletable."""
    from sqlalchemy import select
    from app.db.models.project import Project

    project = await ensure_project(db_session, test_tenant.id, name="Old")
    await db_session.commit()

    gone = await client.delete(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert gone.status_code == 204, gone.text

    row = (await db_session.execute(
        select(Project).where(Project.id == project.id)
    )).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is not None, "must be soft, not hard"

    listed = (await client.get("/api/v1/projects", headers=auth_headers)).json()
    assert "Old" not in [p["name"] for p in listed]


@pytest.mark.asyncio
async def test_unknown_sort_by_is_422_not_a_silent_fallback(client, auth_headers):
    bad = await client.get("/api/v1/projects?sort_by=nonsense", headers=auth_headers)
    assert bad.status_code == 422
