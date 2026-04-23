"""Integration test — /releases/timeline returns gate milestones."""
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_timeline_includes_gates(
    client, auth_headers, db_session, test_tenant,
):
    from app.api.v1.schemas.release_gate import ReleaseGateCreate
    from app.services import release_gate_service, release_defaults

    # Seed lifecycle defaults for the test tenant (not seeded by test_tenant fixture).
    await release_defaults.seed_release_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.flush()

    # Minimal release via API so lifecycle + defaults are applied.
    resp = await client.post(
        "/api/v1/releases",
        headers=auth_headers,
        json={"name": "TL", "release_type": "minor"},
    )
    assert resp.status_code in (200, 201), resp.text
    rid = resp.json()["id"]

    due = datetime(2026, 5, 15, tzinfo=timezone.utc)
    await release_gate_service.create_gate(
        db_session,
        release_id=rid,
        data=ReleaseGateCreate(name="UAT", due_date=due),
        tenant_id=test_tenant.id,
    )
    await db_session.commit()

    resp = await client.get("/api/v1/releases/timeline", headers=auth_headers)
    assert resp.status_code == 200
    entry = next(e for e in resp.json() if e["id"] == rid)
    assert isinstance(entry["gates"], list)
    assert len(entry["gates"]) == 1
    gate = entry["gates"][0]
    assert gate["name"] == "UAT"
    assert gate["status"] == "pending"
    assert gate["due_date"].startswith("2026-05-15")
    assert "id" in gate
