"""Project CRUD. Usage agreements and the entity links have their own files."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.pagination import TOTAL_COUNT_HEADER, Page
from app.db.models.project import Project
from app.services import project_service
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


# ── Finding 1: a PATCH resubmitting an archived team must not 404 ───────────


@pytest.mark.asyncio
async def test_patch_resubmitting_an_archived_team_succeeds(
    client, auth_headers, db_session, test_tenant
):
    """Mirrors environment.operations_group_id (B1): a group can be archived
    after being assigned, and a PATCH editing an unrelated field still
    round-trips the project's own current team_group_id. That must not
    re-validate the group as though it were a new assignment."""
    group = await ensure_user_group(db_session, test_tenant.id, name="Archived Team")
    created = await client.post(
        "/api/v1/projects",
        json={"name": "Roundtrip", "team_group_id": group.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    group.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    patched = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"team_group_id": group.id, "description": "unrelated edit"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["team_group_id"] == group.id
    assert patched.json()["description"] == "unrelated edit"


@pytest.mark.asyncio
async def test_patch_assigning_a_different_archived_team_is_still_refused(
    client, auth_headers, db_session, test_tenant
):
    """The exemption is narrow: it covers resubmitting the stored value, not
    archived groups in general."""
    original = await ensure_user_group(db_session, test_tenant.id, name="Original Team")
    other = await ensure_user_group(db_session, test_tenant.id, name="Other Archived Team")
    created = await client.post(
        "/api/v1/projects",
        json={"name": "No Swap", "team_group_id": original.id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    pid = created.json()["id"]

    other.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    refused = await client.patch(
        f"/api/v1/projects/{pid}",
        json={"team_group_id": other.id},
        headers=auth_headers,
    )
    assert refused.status_code == 404, refused.text


# ── Finding 2: tenant scoping is guarded at every read/write entry point ────


@pytest.mark.asyncio
async def test_another_tenants_project_is_invisible_and_unreachable(
    client, auth_headers, db_session, second_tenant_factory
):
    """Guards _view_query's tenant filter, which backs both list_projects and
    get_project_view. A malformed or missing filter must not surface another
    tenant's project through either call site."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")
    await db_session.commit()

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert theirs.id not in [p["id"] for p in listed.json()]

    fetched = await client.get(f"/api/v1/projects/{theirs.id}", headers=auth_headers)
    assert fetched.status_code == 404, fetched.text


@pytest.mark.asyncio
async def test_another_tenants_project_cannot_be_deleted(
    client, auth_headers, db_session, second_tenant_factory
):
    """Guards get_project's tenant filter. Unlike PATCH, DELETE never re-reads
    the row through a tenant-filtered query afterwards, so it is the one path
    where dropping this filter is directly observable: the row would be
    silently soft-deleted instead of 404ing."""
    other_tenant, _other_admin = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Not Yours")
    await db_session.commit()

    deleted = await client.delete(f"/api/v1/projects/{theirs.id}", headers=auth_headers)
    assert deleted.status_code == 404, deleted.text

    row = (
        await db_session.execute(select(Project).where(Project.id == theirs.id))
    ).scalar_one()
    await db_session.refresh(row)
    assert row.deleted_at is None, "must not be deleted by another tenant's admin"


@pytest.mark.asyncio
async def test_name_uniqueness_is_scoped_per_tenant(
    client, auth_headers, db_session, second_tenant_factory
):
    """Guards _assert_name_free's tenant filter. Two tenants may each have a
    project named the same thing; if the filter were dropped, tenant B
    creating 'Mortgage' would 409 against tenant A's row — which also leaks
    the existence of A's project through the error message."""
    ours = await client.post(
        "/api/v1/projects", json={"name": "Mortgage"}, headers=auth_headers
    )
    assert ours.status_code == 201, ours.text

    other_tenant, other_admin = await second_tenant_factory()
    other_login = await client.post(
        "/api/v1/auth/login",
        json={
            "username": other_admin.username,
            "password": "password123",
            "tenant_slug": other_tenant.slug,
        },
    )
    assert other_login.status_code == 200, other_login.text
    other_headers = {
        "Authorization": f"Bearer {other_login.json()['access_token']}"
    }

    theirs = await client.post(
        "/api/v1/projects", json={"name": "Mortgage"}, headers=other_headers
    )
    assert theirs.status_code == 201, theirs.text


# ── Finding 4: list ordering — case fold and the id tiebreaker ──────────────


@pytest.mark.asyncio
async def test_default_sort_folds_case_over_mixed_case_names(
    client, auth_headers
):
    """Both engines here collate by byte value, which would put 'Zebra'
    before 'apple'. Asserted on rendered row order, not the emitted SQL —
    an assertion on the query string stays green while the order users see
    is wrong."""
    for name in ["Zebra", "apple", "melon"]:
        created = await client.post(
            "/api/v1/projects", json={"name": name}, headers=auth_headers
        )
        assert created.status_code == 201, created.text

    listed = await client.get("/api/v1/projects", headers=auth_headers)
    assert [p["name"] for p in listed.json()] == ["apple", "melon", "Zebra"]


@pytest.mark.asyncio
async def test_list_projects_folds_case_when_no_client_sort_is_given(
    db_session, test_tenant
):
    """`GET /api/v1/projects` always resolves a Sort (its `sorting()` default
    is "name"), and apply_sort's own case fold on that whitelisted column
    masks list_projects' own `func.lower(Project.name)` when reached through
    the API — so an API-level rendered-order assertion alone cannot catch
    that clause being dropped. list_projects is called directly here, with
    no sort, the same way any future non-API caller would, so its own fold
    is the only one in effect."""
    for name in ["Zebra", "apple", "melon"]:
        db_session.add(Project(tenant_id=test_tenant.id, name=name))
    await db_session.flush()

    views, _total = await project_service.list_projects(
        db_session, test_tenant.id, page=Page(limit=10, offset=0)
    )
    assert [v.project.name for v in views] == ["apple", "melon", "Zebra"]


@pytest.mark.asyncio
async def test_paging_over_tied_names_sees_each_row_once(db_session, test_tenant):
    """Every project shares a name, so `ORDER BY lower(name)` alone leaves
    ties. Without the `Project.id` tiebreaker, LIMIT/OFFSET can return a row
    on more than one page and drop another entirely. Bypasses the API's own
    name-uniqueness check (enforced in the service, not the DB) the same way
    test_pagination_ordering.py bypasses environment_service for the same
    reason."""
    total_rows = 21
    for _ in range(total_rows):
        db_session.add(Project(tenant_id=test_tenant.id, name="identical"))
    await db_session.flush()

    seen: list[int] = []
    page_size = 5
    offset = 0
    while True:
        views, total = await project_service.list_projects(
            db_session, test_tenant.id, page=Page(limit=page_size, offset=offset)
        )
        assert total == total_rows
        if not views:
            break
        seen.extend(v.project.id for v in views)
        offset += page_size

    assert len(seen) == total_rows, f"expected {total_rows} rows, saw {len(seen)}"
    assert len(set(seen)) == total_rows, "a row was returned on more than one page"


# ── Finding 5: is_active and search are unexercised ─────────────────────────


@pytest.mark.asyncio
async def test_search_filters_by_name_case_insensitively(client, auth_headers):
    for name in ["Mortgage Alpha", "Other Beta"]:
        created = await client.post(
            "/api/v1/projects", json={"name": name}, headers=auth_headers
        )
        assert created.status_code == 201, created.text

    found = await client.get(
        "/api/v1/projects?search=mortgage", headers=auth_headers
    )
    assert found.status_code == 200, found.text
    assert [p["name"] for p in found.json()] == ["Mortgage Alpha"]


@pytest.mark.asyncio
async def test_is_active_filter_reports_the_filtered_total_not_the_whole_tenant(
    client, auth_headers
):
    """Discriminates against moving is_active filtering to Python after
    fetch_page_rows: that would leave the returned rows looking right (the
    page comfortably holds every row) while X-Total-Count still describes
    the unfiltered tenant, not the filtered set — the windowing bug the
    plan explicitly warns against."""
    for name in ["Active One", "Active Two", "Active Three"]:
        created = await client.post(
            "/api/v1/projects", json={"name": name}, headers=auth_headers
        )
        assert created.status_code == 201, created.text
    for name in ["Retired One", "Retired Two"]:
        created = await client.post(
            "/api/v1/projects",
            json={"name": name, "is_active": False},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text

    active_only = await client.get(
        "/api/v1/projects?is_active=true", headers=auth_headers
    )
    assert active_only.status_code == 200, active_only.text
    assert len(active_only.json()) == 3
    assert int(active_only.headers[TOTAL_COUNT_HEADER]) == 3

    inactive_only = await client.get(
        "/api/v1/projects?is_active=false", headers=auth_headers
    )
    assert inactive_only.status_code == 200, inactive_only.text
    assert len(inactive_only.json()) == 2
    assert int(inactive_only.headers[TOTAL_COUNT_HEADER]) == 2


@pytest.mark.asyncio
async def test_an_archived_teams_name_still_renders_on_its_projects(
    client, auth_headers, db_session, test_tenant
):
    """_view_query's UserGroup join deliberately does NOT filter deleted_at.

    Blanking the name would lose information the row still carries — the same
    call B3a made for a soft-deleted operations group. Added after the Task 3
    fix review found nothing discriminated here: adding
    `UserGroup.deleted_at.is_(None)` to that join left every project test green,
    including the two that look like they cover it (one never archives the
    group, the other never asserts team_group_name at all).

    Note this is the OPPOSITE judgement from _agreement_query, whose joins DO
    filter deleted_at. There we decide whether a row whose counterparty is gone
    should appear; here we render the name of an archived thing on a live row.
    """
    group = await ensure_user_group(db_session, test_tenant.id, name="Wound Down Team")
    await db_session.commit()
    pid = (await client.post(
        "/api/v1/projects",
        json={"name": "Still Running", "team_group_id": group.id},
        headers=auth_headers,
    )).json()["id"]

    # Archived directly rather than through delete_group, which refuses while
    # anything still references the group — the state we need is the archived
    # one, not the route that produces it.
    from datetime import datetime, timezone

    group.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    still = await client.get(f"/api/v1/projects/{pid}", headers=auth_headers)
    assert still.status_code == 200, still.text
    assert still.json()["team_group_name"] == "Wound Down Team"
