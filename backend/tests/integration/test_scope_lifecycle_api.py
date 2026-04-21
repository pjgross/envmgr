"""HTTP integration tests for scope-item lifecycle: moves, history, KPIs, admin rules."""
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.db.models.release_change_history import ReleaseChangeReleaseHistory
from app.services import scope_change_rule_service


# ── Local helpers ─────────────────────────────────────────────────────────────

async def _make_lifecycle_template(db_session: AsyncSession, tenant_id: int, name: str = "Std") -> LifecycleTemplate:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id,
        entity_type="release",
        name=name,
        is_default=False,
        definition={
            "states": [
                {"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False},
                {"key": "approved", "label": "Approved", "is_initial": False, "is_terminal": False},
            ],
            "transitions": [
                {"from_state": "draft", "to_state": "approved", "allowed_roles": ["Admin"]},
            ],
            "field_permissions": {
                "draft": {"standard_fields": {}, "custom_fields": {}},
                "approved": {"standard_fields": {}, "custom_fields": {}},
            },
        },
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _create_release_via_api(client: AsyncClient, headers: dict, name: str = "R") -> int:
    resp = await client.post(
        "/api/v1/releases", headers=headers,
        json={"name": name, "release_type": "Major"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_scope_item(
    client: AsyncClient,
    headers: dict,
    release_id: int,
    title: str = "Item",
    change_kind: str = "story",
    **extra,
) -> dict:
    payload = {"title": title, "change_kind": change_kind, **extra}
    resp = await client.post(
        f"/api/v1/releases/{release_id}/changes", headers=headers, json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def release_lifecycle(db_session: AsyncSession, test_tenant):
    """A default LifecycleTemplate for the test_tenant (needed for POST /releases)."""
    tpl = await _make_lifecycle_template(db_session, test_tenant.id, name="API-Test-Lifecycle")
    # Mark as is_default so release creation picks it up automatically
    tpl.is_default = True
    await db_session.commit()
    await db_session.refresh(tpl)
    return tpl


# ── 1. move endpoint round-trip ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_move_endpoint_round_trip(client, auth_headers, release_lifecycle):
    rid_a = await _create_release_via_api(client, auth_headers, name="MoveA")
    rid_b = await _create_release_via_api(client, auth_headers, name="MoveB")

    item = await _create_scope_item(client, auth_headers, rid_a)
    change_id = item["id"]

    # Move to rid_b
    mv = await client.post(
        f"/api/v1/release-changes/{change_id}/move",
        headers=auth_headers,
        json={"release_id": rid_b},
    )
    assert mv.status_code == 200, mv.text
    assert mv.json()["release_id"] == rid_b

    # GET /release-history should have 2 rows: initial assign + move
    hist = await client.get(
        f"/api/v1/release-changes/{change_id}/release-history",
        headers=auth_headers,
    )
    assert hist.status_code == 200, hist.text
    rows = hist.json()
    assert len(rows) == 2
    assert rows[0]["from_release_id"] is None
    assert rows[0]["to_release_id"] == rid_a
    assert rows[1]["from_release_id"] == rid_a
    assert rows[1]["to_release_id"] == rid_b


# ── 2. move endpoint to backlog ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_move_endpoint_to_backlog(client, auth_headers, release_lifecycle):
    rid = await _create_release_via_api(client, auth_headers, name="BacklogR")
    item = await _create_scope_item(client, auth_headers, rid)
    change_id = item["id"]

    mv = await client.post(
        f"/api/v1/release-changes/{change_id}/move",
        headers=auth_headers,
        json={"release_id": None},
    )
    assert mv.status_code == 200, mv.text
    assert mv.json()["release_id"] is None


# ── 3. move endpoint rejects jira-sourced items ───────────────────────────────

@pytest.mark.asyncio
async def test_move_endpoint_rejects_jira_source(client, auth_headers, db_session, test_tenant, release_lifecycle):
    rid_a = await _create_release_via_api(client, auth_headers, name="JiraA")
    rid_b = await _create_release_via_api(client, auth_headers, name="JiraB")

    item = await _create_scope_item(client, auth_headers, rid_a, title="Jira Item")
    change_id = item["id"]

    # Patch source to 'jira' directly via DB
    row = (
        await db_session.execute(select(ReleaseChange).where(ReleaseChange.id == change_id))
    ).scalar_one()
    row.source = "jira"
    await db_session.flush()

    mv = await client.post(
        f"/api/v1/release-changes/{change_id}/move",
        headers=auth_headers,
        json={"release_id": rid_b},
    )
    assert mv.status_code == 422, mv.text


# ── 4. backlog listing returns only unassigned items ──────────────────────────

@pytest.mark.asyncio
async def test_backlog_listing_returns_only_unassigned(client, auth_headers, release_lifecycle):
    rid = await _create_release_via_api(client, auth_headers, name="BacklogFilter")

    # Create an item in a release
    in_release = await _create_scope_item(client, auth_headers, rid, title="In release")

    # Move one to the backlog
    await client.post(
        f"/api/v1/release-changes/{in_release['id']}/move",
        headers=auth_headers,
        json={"release_id": None},
    )

    # Create another item that stays in the release
    await _create_scope_item(client, auth_headers, rid, title="Stays in release")

    # GET /release-changes?backlog=true should return only backlog items
    resp = await client.get(
        "/api/v1/release-changes", headers=auth_headers, params={"backlog": "true"},
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert all(item["release_id"] is None for item in items)
    titles = [i["title"] for i in items]
    assert "In release" in titles
    assert "Stays in release" not in titles


# ── 5. release-history endpoint returns list ─────────────────────────────────

@pytest.mark.asyncio
async def test_release_history_endpoint_returns_list(client, auth_headers, release_lifecycle):
    rid = await _create_release_via_api(client, auth_headers, name="HistEndpointR")
    item = await _create_scope_item(client, auth_headers, rid)
    change_id = item["id"]

    resp = await client.get(
        f"/api/v1/release-changes/{change_id}/release-history",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    # At minimum the initial assignment row exists.
    assert len(rows) >= 1
    assert rows[0]["from_release_id"] is None
    assert rows[0]["to_release_id"] == rid


# ── 6. status-history endpoint returns list ───────────────────────────────────

@pytest.mark.asyncio
async def test_status_history_endpoint_returns_list(client, auth_headers, release_lifecycle):
    rid = await _create_release_via_api(client, auth_headers, name="StatusHistR")
    item = await _create_scope_item(
        client, auth_headers, rid, title="Has status", external_status="Open",
    )
    change_id = item["id"]

    resp = await client.get(
        f"/api/v1/release-changes/{change_id}/status-history",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["from_status"] is None
    assert rows[0]["to_status"] == "Open"


# ── 7. release soft-delete preserves scope items (FK SET NULL is DB-level safety net) ───

@pytest.mark.asyncio
async def test_release_delete_drops_scope_items_to_backlog(
    client, auth_headers, db_session, test_tenant, release_lifecycle,
):
    """Deleting a release (soft-delete) unlinks its scope items to the backlog
    and writes a history row recording the unlink, rather than leaving the
    items stranded on a soft-deleted release."""
    rid = await _create_release_via_api(client, auth_headers, name="DeleteR")
    item = await _create_scope_item(client, auth_headers, rid, title="Scope follows to backlog")
    change_id = item["id"]

    del_resp = await client.delete(f"/api/v1/releases/{rid}", headers=auth_headers)
    assert del_resp.status_code == 204, del_resp.text

    db_session.expire_all()
    row = (
        await db_session.execute(
            select(ReleaseChange).where(ReleaseChange.id == change_id)
        )
    ).scalar_one()
    assert row is not None, "Scope item must survive release soft-delete"
    assert row.release_id is None, "Scope item must be in the backlog after its release is deleted"

    # A history row must record the unlink.
    hist = (
        await db_session.execute(
            select(ReleaseChangeReleaseHistory)
            .where(ReleaseChangeReleaseHistory.change_id == change_id)
            .order_by(ReleaseChangeReleaseHistory.moved_at)
        )
    ).scalars().all()
    assert len(hist) >= 2, "Expect initial-assign + delete-driven unlink history rows"
    assert hist[-1].from_release_id == rid
    assert hist[-1].to_release_id is None


# ── 8. scope_additions_count counts only counting kinds ──────────────────────

@pytest.mark.asyncio
async def test_scope_additions_count_counts_only_counting_kinds(
    client, auth_headers, db_session, test_tenant, release_lifecycle,
):
    # Seed default rules (story=True, defect=False, task=False, spike=False)
    await scope_change_rule_service.seed_default_rules(db_session, test_tenant.id)
    await db_session.flush()

    rid = await _create_release_via_api(client, auth_headers, name="KPIRelease")

    # 2 stories (count) + 2 defects (don't count)
    await _create_scope_item(client, auth_headers, rid, title="Story 1", change_kind="story")
    await _create_scope_item(client, auth_headers, rid, title="Story 2", change_kind="story")
    await _create_scope_item(client, auth_headers, rid, title="Bug 1", change_kind="defect")
    await _create_scope_item(client, auth_headers, rid, title="Bug 2", change_kind="defect")

    # GET /releases (list) should show scope_additions_count=2 (stories only)
    resp = await client.get("/api/v1/releases", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    releases = resp.json()["items"] if "items" in resp.json() else resp.json()
    release = next((r for r in releases if r["id"] == rid), None)
    assert release is not None, "Release not found in list"
    assert release["scope_additions_count"] == 2, f"Expected 2, got {release['scope_additions_count']}"


# ── 9. scope_change_count includes removals ───────────────────────────────────

@pytest.mark.asyncio
async def test_scope_change_count_includes_removals(
    client, auth_headers, db_session, test_tenant, release_lifecycle,
):
    await scope_change_rule_service.seed_default_rules(db_session, test_tenant.id)
    await db_session.flush()

    rid_a = await _create_release_via_api(client, auth_headers, name="RemA")
    rid_b = await _create_release_via_api(client, auth_headers, name="RemB")

    # Add 2 stories to rid_a
    item1 = await _create_scope_item(client, auth_headers, rid_a, title="Story X", change_kind="story")
    item2 = await _create_scope_item(client, auth_headers, rid_a, title="Story Y", change_kind="story")

    # Move story X out of rid_a → creates a "removal" from rid_a
    await client.post(
        f"/api/v1/release-changes/{item1['id']}/move",
        headers=auth_headers,
        json={"release_id": rid_b},
    )

    resp = await client.get("/api/v1/releases", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    releases = resp.json()["items"] if "items" in resp.json() else resp.json()
    release_a = next((r for r in releases if r["id"] == rid_a), None)
    assert release_a is not None

    # rid_a: 2 additions (initial stories), 1 removal (moved out)
    assert release_a["scope_additions_count"] == 2
    assert release_a["scope_removals_count"] >= 1
    assert release_a["scope_change_count"] == release_a["scope_additions_count"] + release_a["scope_removals_count"]


# ── 10. admin list rules returns four seeded kinds ────────────────────────────

@pytest.mark.asyncio
async def test_admin_list_rules_returns_four(client, auth_headers, db_session, test_tenant, release_lifecycle):
    # The test_tenant fixture creates a tenant directly (no seed), so seed here.
    await scope_change_rule_service.seed_default_rules(db_session, test_tenant.id)
    await db_session.flush()

    resp = await client.get("/api/v1/tenant/scope-change-rules", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    rules = resp.json()
    assert len(rules) == 4
    kinds = {r["change_kind"] for r in rules}
    assert kinds == {"story", "defect", "task", "spike"}


# ── 11. admin PUT rules upserts correctly ────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_put_rules_upserts(client, auth_headers, db_session, test_tenant, release_lifecycle):
    # Seed so we have the four standard rules.
    await scope_change_rule_service.seed_default_rules(db_session, test_tenant.id)
    await db_session.flush()

    # Confirm defect starts as False.
    get_resp = await client.get("/api/v1/tenant/scope-change-rules", headers=auth_headers)
    rules_before = {r["change_kind"]: r["counts_as_scope_change"] for r in get_resp.json()}
    assert rules_before["defect"] is False

    # Flip defect to True.
    put_resp = await client.put(
        "/api/v1/tenant/scope-change-rules",
        headers=auth_headers,
        json={"rules": [{"change_kind": "defect", "counts_as_scope_change": True}]},
    )
    assert put_resp.status_code == 200, put_resp.text

    # GET should now show defect=True.
    get_after = await client.get("/api/v1/tenant/scope-change-rules", headers=auth_headers)
    assert get_after.status_code == 200, get_after.text
    rules_after = {r["change_kind"]: r["counts_as_scope_change"] for r in get_after.json()}
    assert rules_after["defect"] is True
    # Others should be unchanged.
    assert rules_after["story"] is True
