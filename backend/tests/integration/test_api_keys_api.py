"""/api/v1/api-keys — create (raw shown once), list, revoke."""
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
