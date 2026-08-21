"""Phase 9 C4 Task 4 — rollback rehearsals, over HTTP.

Covers the POST/GET round trip, the extra="forbid" schema guard, and — the
reason this file exists rather than relying on reasoning alone — that
`GET/POST /systems/{system_id}/rollback-rehearsals` actually reaches the
rehearsal routes rather than being swallowed by `GET /systems/{system_id}`,
the B6 "literal segment behind a catch-all" hazard.
"""
import pytest
import pytest_asyncio

from app.db.models.system import System


@pytest_asyncio.fixture
async def system(db_session, test_tenant) -> System:
    s = System(tenant_id=test_tenant.id, name="Payments API")
    db_session.add(s)
    await db_session.commit()
    await db_session.refresh(s)
    return s


@pytest.mark.asyncio
async def test_a_rehearsal_round_trips_over_http(client, auth_headers, system):
    post = await client.post(
        f"/api/v1/systems/{system.id}/rollback-rehearsals",
        json={"rehearsed_at": "2026-08-01T00:00:00Z", "outcome": "passed",
              "notes": "Dry-run in staging"},
        headers=auth_headers,
    )
    assert post.status_code == 201, post.text
    body = post.json()
    assert body["system_id"] == system.id
    assert body["outcome"] == "passed"
    assert body["state"] == "current"
    assert body["rehearsed_by_username"] is not None

    got = await client.get(
        f"/api/v1/systems/{system.id}/rollback-rehearsals", headers=auth_headers
    )
    assert got.status_code == 200
    rows = got.json()
    assert len(rows) == 1
    assert rows[0]["id"] == body["id"]


@pytest.mark.asyncio
async def test_an_unknown_key_is_a_422(client, auth_headers, system):
    """The schema is extra='forbid', so a typo cannot be silently dropped."""
    resp = await client.post(
        f"/api/v1/systems/{system.id}/rollback-rehearsals",
        json={"rehearsed_at": "2026-08-01T00:00:00Z", "outcome": "passed",
              "outcom": "typo"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_outcome_is_a_422(client, auth_headers, system):
    resp = await client.post(
        f"/api/v1/systems/{system.id}/rollback-rehearsals",
        json={"rehearsed_at": "2026-08-01T00:00:00Z", "outcome": "sort-of"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_system_by_id_still_works_beside_the_new_route(client, auth_headers, system):
    """The routing trap this file exists to catch: a literal segment behind a
    `/{system_id}` catch-all. Proves BOTH directions reach their own handler —
    plain `GET /systems/{id}` still returns the system, not a 422 from a
    rehearsal route swallowing it, and vice versa (previous tests)."""
    resp = await client.get(f"/api/v1/systems/{system.id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == system.id
