"""/api/v1/api-keys — create (raw shown once), list, revoke."""
import json

import pytest


@pytest.mark.asyncio
async def test_create_list_revoke_roundtrip(client, auth_headers):
    # Create
    r = await client.post(
        "/api/v1/api-keys", headers=auth_headers,
        json={"name": "CI", "scopes": ["webhooks:deployment"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "CI"
    assert body["raw_key"].startswith("em_")
    key_id = body["id"]

    # List — raw_key MUST NOT appear
    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(k["id"] == key_id for k in items)
    for k in items:
        assert "raw_key" not in k
        assert "key_hash" not in k

    # Revoke
    r = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth_headers)
    assert r.status_code == 204

    # List — no longer appears
    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert all(k["id"] != key_id for k in r.json())


@pytest.mark.asyncio
async def test_create_rejects_unknown_scope(client, auth_headers):
    # A typo'd scope must 422 at create time, naming the offending scope
    # and the valid ones — the whole point being that the plaintext key
    # is otherwise shown once and every call with it silently 403s later
    # with no hint a typo was the cause.
    r = await client.post(
        "/api/v1/api-keys", headers=auth_headers,
        json={"name": "Typo", "scopes": ["webhooks:deploymnet"]},
    )
    assert r.status_code == 422, r.text
    detail = json.dumps(r.json())
    assert "webhooks:deploymnet" in detail
    assert "webhooks:deployment" in detail
    assert "webhooks:release" in detail
