"""`project.priority_rank` — LOWER WINS, and null means unranked.

Null is a real state, not a missing value: no project has a rank on first
deploy, and there is no backfill. A4's verdict treats unranked as
"priority does not separate these", never as "loses".
"""
import pytest
from httpx import AsyncClient

from tests.factories import ensure_project


@pytest.mark.asyncio
async def test_a_new_project_is_unranked(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/projects", json={"name": "Unranked By Default"}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["priority_rank"] is None


@pytest.mark.asyncio
async def test_a_rank_can_be_set_and_read_back(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Ranked")

    patched = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 1}, headers=auth_headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["priority_rank"] == 1

    read = await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert read.json()["priority_rank"] == 1


@pytest.mark.asyncio
async def test_a_rank_can_be_cleared_back_to_unranked(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    """An explicit null clears it. `update_project` keys on model_fields_set,
    so an OMITTED key means "leave alone" — the contract B1 gave expires_at."""
    project = await ensure_project(db_session, test_tenant.id, name="Clearable")
    await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 3}, headers=auth_headers
    )

    cleared = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": None}, headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["priority_rank"] is None


@pytest.mark.asyncio
async def test_omitting_the_rank_leaves_it_alone(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Untouched")
    await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 2}, headers=auth_headers
    )

    renamed = await client.patch(
        f"/api/v1/projects/{project.id}", json={"name": "Untouched Renamed"},
        headers=auth_headers,
    )
    assert renamed.json()["priority_rank"] == 2


@pytest.mark.asyncio
async def test_a_rank_below_one_is_refused(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    """Rank 1 is the highest. Zero and negatives are not "even higher" — they
    are a caller who has guessed the direction, and guessing wrong silently is
    the whole reason this field is validated."""
    project = await ensure_project(db_session, test_tenant.id, name="Bad Rank")
    resp = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 0}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_another_tenants_project_rank_is_404_not_403(
    client: AsyncClient, auth_headers: dict, db_session, second_tenant_factory
):
    other_tenant, _ = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")

    resp = await client.patch(
        f"/api/v1/projects/{theirs.id}", json={"priority_rank": 1}, headers=auth_headers
    )
    assert resp.status_code == 404, resp.text
