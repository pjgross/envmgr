"""End-to-end happy-path for Enterprise Releases (spec §6 Acceptance)."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.services import release_defaults


@pytest.mark.asyncio
async def test_enterprise_release_full_flow(client, auth_headers, test_tenant, db_session):
    """Create enterprise, add 2 projects, request+accept both, transition past lockdown,
    add 3rd project (late_scope=True), generate report.
    """
    # ── 0. Seed release lifecycle templates for this tenant ───────────────────
    # test_tenant is created directly (not via tenant_service) so defaults must
    # be seeded explicitly here.
    await release_defaults.seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    # ── 1. Discover the enterprise lifecycle template id for this tenant ──────
    ent_tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "release",
            LifecycleTemplate.applies_to_kind == "enterprise",
        )
    )).scalar_one()

    # Find the default project-kind template.
    proj_tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == test_tenant.id,
            LifecycleTemplate.entity_type == "release",
            LifecycleTemplate.applies_to_kind == "project",
            LifecycleTemplate.is_default.is_(True),
        )
    )).scalar_one()

    # ── 2. Create enterprise release ──────────────────────────────────────────
    ent_resp = await client.post(
        "/api/v1/releases",
        json={
            "name": "ENT-2026-Q1",
            "release_type": "Major",
            "release_kind": "enterprise",
            "lifecycle_template_id": ent_tpl.id,
            "target_date": "2026-06-01T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert ent_resp.status_code in (200, 201), ent_resp.text
    enterprise_id = ent_resp.json()["id"]

    # ── 3. Create 2 project releases (Alpha, Beta) with 1 scope item each ────
    proj_ids = []
    for n in ("Alpha", "Beta"):
        r = await client.post(
            "/api/v1/releases",
            json={
                "name": n,
                "release_type": "Major",
                "release_kind": "project",
                "lifecycle_template_id": proj_tpl.id,
                "target_date": "2026-05-15T00:00:00Z",
            },
            headers=auth_headers,
        )
        assert r.status_code in (200, 201), r.text
        proj_ids.append(r.json()["id"])

    for i, pid in enumerate(proj_ids):
        sr = await client.post(
            f"/api/v1/releases/{pid}/changes",
            json={
                "external_key": f"P{i}-1",
                "title": f"Feature {i}",
                "change_kind": "story",
            },
            headers=auth_headers,
        )
        assert sr.status_code in (200, 201), sr.text

    # ── 4. Request + accept both projects (pre-lockdown → late_scope=False) ───
    for pid in proj_ids:
        req = await client.post(
            f"/api/v1/releases/{enterprise_id}/memberships",
            json={"project_release_id": pid},
            headers=auth_headers,
        )
        assert req.status_code == 201, req.text
        mid = req.json()["id"]
        acc = await client.post(
            f"/api/v1/releases/{enterprise_id}/memberships/{mid}/accept",
            headers=auth_headers,
        )
        assert acc.status_code == 200, acc.text
        assert acc.json()["late_scope"] is False

    # ── 5. Transition enterprise past lockdown ─────────────────────────────────
    # Enterprise lifecycle: draft → planning → admission_open → admission_closed [lockdown]
    #                       → integration_testing → ...
    # admission_closed is the lockdown state; integration_testing is past it.
    for target in ("planning", "admission_open", "admission_closed", "integration_testing"):
        t = await client.post(
            f"/api/v1/releases/{enterprise_id}/transition",
            json={"to_state": target},
            headers=auth_headers,
        )
        assert t.status_code == 200, f"transition to {target} failed: {t.text}"
        assert t.json()["status"] == target

    # ── 6. Create 3rd project (Gamma) and accept — should get late_scope=True ─
    r = await client.post(
        "/api/v1/releases",
        json={
            "name": "Gamma",
            "release_type": "Major",
            "release_kind": "project",
            "lifecycle_template_id": proj_tpl.id,
            "target_date": "2026-05-20T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert r.status_code in (200, 201), r.text
    gamma_id = r.json()["id"]

    sr = await client.post(
        f"/api/v1/releases/{gamma_id}/changes",
        json={"external_key": "G-1", "title": "Late feature", "change_kind": "story"},
        headers=auth_headers,
    )
    assert sr.status_code in (200, 201), sr.text

    req = await client.post(
        f"/api/v1/releases/{enterprise_id}/memberships",
        json={"project_release_id": gamma_id},
        headers=auth_headers,
    )
    assert req.status_code == 201, req.text
    mid = req.json()["id"]

    acc = await client.post(
        f"/api/v1/releases/{enterprise_id}/memberships/{mid}/accept",
        headers=auth_headers,
    )
    assert acc.status_code == 200, acc.text
    assert acc.json()["late_scope"] is True

    # ── 7. Generate report and validate ──────────────────────────────────────
    report = await client.get(
        f"/api/v1/releases/{enterprise_id}/report",
        headers=auth_headers,
    )
    assert report.status_code == 200, report.text
    body = report.json()

    # All three projects appear as members
    member_names = {m["project_release_name"] for m in body["members"]}
    assert member_names == {"Alpha", "Beta", "Gamma"}

    # All scope items from every accepted project appear in scope_by_project
    all_keys = {
        it["external_key"]
        for items in body["scope_by_project"].values()
        for it in items
    }
    assert all_keys == {"P0-1", "P1-1", "G-1"}
