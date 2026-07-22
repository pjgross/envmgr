"""Integration tests for the tenant RAID config endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_raid_config_returns_default(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v1/tenant/raid-config", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["probability_scale"]) == 5
    assert len(body["impact_scale"]) == 5
    assert len(body["rag_bands"]) == 3
    assert body["probability_scale"][0]["label"] == "Rare"


@pytest.mark.asyncio
async def test_put_raid_config_persists(client: AsyncClient, auth_headers):
    new_bands = [
        {"rag": "green", "min": 1, "max": 3, "color": "#4caf50"},
        {"rag": "amber", "min": 4, "max": 9, "color": "#ff9800"},
        {"rag": "red", "min": 10, "max": 25, "color": "#f44336"},
    ]
    put = await client.put(
        "/api/v1/tenant/raid-config",
        headers=auth_headers,
        json={"rag_bands": new_bands},
    )
    assert put.status_code == 200, put.text
    assert put.json()["rag_bands"][1]["max"] == 9
    # persisted
    got = await client.get("/api/v1/tenant/raid-config", headers=auth_headers)
    assert got.json()["rag_bands"][2]["min"] == 10


@pytest.mark.asyncio
async def test_raid_config_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/tenant/raid-config")
    assert resp.status_code in (401, 403)
