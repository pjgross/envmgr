"""One live hyper-care phase per release; template hyper-care phases are laid
FORWARD from target_date while test phases still end on it."""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


@pytest_asyncio.fixture
async def release(db_session, test_tenant, test_user):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="release", name="HC", is_default=True,
        applies_to_kind="project",
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True, "is_terminal": False}],
                    "transitions": [], "field_permissions": {"draft": {"standard_fields": {}, "custom_fields": {}}}},
    )
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(tenant_id=test_tenant.id, name="R", release_type="Major", release_kind="project",
                  lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id)
    db_session.add(rel)
    await db_session.commit()
    await db_session.refresh(rel)
    return rel


@pytest.mark.asyncio
async def test_kind_defaults_to_test_and_round_trips(client, auth_headers, release):
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "SIT"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["kind"] == "test"
    hc = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                           json={"name": "Hyper-care", "kind": "hypercare"})
    assert hc.status_code == 201, hc.text
    assert hc.json()["kind"] == "hypercare"
    listed = (await client.get(f"/api/v1/releases/{release.id}/phases", headers=auth_headers)).json()
    assert {p["name"]: p["kind"] for p in listed} == {"SIT": "test", "Hyper-care": "hypercare"}


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_422(client, auth_headers, release):
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "X", "kind": "warranty"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_second_live_hypercare_phase_is_refused_naming_the_first(client, auth_headers, release):
    first = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                               json={"name": "Hyper-care", "kind": "hypercare"})).json()
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "Second", "kind": "hypercare"})
    assert resp.status_code == 422, resp.text
    assert first["name"] in resp.json()["detail"]


@pytest.mark.asyncio
async def test_changing_a_test_phase_to_hypercare_obeys_the_rule(client, auth_headers, release):
    await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                      json={"name": "Hyper-care", "kind": "hypercare"})
    sit = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "SIT"})).json()
    resp = await client.put(f"/api/v1/phases/{sit['id']}", headers=auth_headers, json={"kind": "hypercare"})
    assert resp.status_code == 422, resp.text
    # Updating the hyper-care phase itself (same row) is not a second one.
    hc = next(p for p in (await client.get(f"/api/v1/releases/{release.id}/phases",
                                           headers=auth_headers)).json() if p["kind"] == "hypercare")
    ok = await client.put(f"/api/v1/phases/{hc['id']}", headers=auth_headers,
                          json={"kind": "hypercare", "name": "Hyper-care (2 weeks)"})
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_a_soft_deleted_hypercare_phase_frees_the_slot(client, auth_headers, release):
    first = (await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                               json={"name": "Hyper-care", "kind": "hypercare"})).json()
    assert (await client.delete(f"/api/v1/phases/{first['id']}", headers=auth_headers)).status_code == 204
    resp = await client.post(f"/api/v1/releases/{release.id}/phases", headers=auth_headers,
                             json={"name": "Again", "kind": "hypercare"})
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_template_hypercare_phase_runs_forward_from_target_date(client, auth_headers, db_session, test_tenant):
    from app.services.release_defaults import seed_release_defaults_for_tenant
    await seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()
    tpl = await client.post("/api/v1/release-templates", headers=auth_headers, json={
        "name": "With hyper-care", "release_type": "Major",
        "phases": [
            {"name": "SIT", "order": 1, "default_duration_days": 5, "activities": []},
            {"name": "UAT", "order": 2, "default_duration_days": 3, "activities": []},
            {"name": "Hyper-care", "order": 3, "default_duration_days": 14, "activities": [],
             "kind": "hypercare"},
        ],
        "gates": [],
    })
    assert tpl.status_code == 201, tpl.text
    target = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    rel = await client.post(f"/api/v1/release-templates/{tpl.json()['id']}/instantiate",
                            headers=auth_headers,
                            json={"name": "R1", "target_date": target.isoformat()})
    assert rel.status_code == 201, rel.text
    phases = {p["name"]: p for p in (await client.get(
        f"/api/v1/releases/{rel.json()['id']}/phases", headers=auth_headers)).json()}
    assert datetime.fromisoformat(phases["UAT"]["end_date"]) == target
    assert datetime.fromisoformat(phases["SIT"]["end_date"]) == target - timedelta(days=3)
    assert phases["Hyper-care"]["kind"] == "hypercare"
    assert datetime.fromisoformat(phases["Hyper-care"]["start_date"]) == target
    assert datetime.fromisoformat(phases["Hyper-care"]["end_date"]) == target + timedelta(days=14)
