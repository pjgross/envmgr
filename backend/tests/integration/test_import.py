"""Integration tests for Excel Import (M5)."""
import io

import openpyxl
import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Excel file helpers
# ---------------------------------------------------------------------------


def make_environment_excel(rows: list[dict]) -> bytes:
    """Build an Excel workbook with environment rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Type", "Description"])
    for row in rows:
        ws.append([row.get("Name", ""), row.get("Type", ""), row.get("Description", "")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_environment_excel_no_name_col(rows: list[dict]) -> bytes:
    """Build an Excel workbook WITHOUT a Name column — for error testing."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Type", "Description"])
    for row in rows:
        ws.append([row.get("Type", ""), row.get("Description", "")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_system_excel(rows: list[dict]) -> bytes:
    """Build an Excel workbook with system rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Description", "GitHub URL"])
    for row in rows:
        ws.append([row.get("Name", ""), row.get("Description", ""), row.get("GitHub URL", "")])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests — Environments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_environments(client: AsyncClient, auth_headers):
    """POST /import/environments with a valid file creates new environments."""
    file_bytes = make_environment_excel([
        {"Name": "ImportedEnv1", "Type": "uat", "Description": "First imported env"},
        {"Name": "ImportedEnv2", "Type": "staging"},
    ])

    resp = await client.post(
        "/api/v1/import/environments",
        headers=auth_headers,
        files={"file": ("envs.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["errors"] == []

    # Verify environments exist via list endpoint
    list_resp = await client.get("/api/v1/environments/", headers=auth_headers)
    names = [e["name"] for e in list_resp.json()]
    assert "ImportedEnv1" in names
    assert "ImportedEnv2" in names


@pytest.mark.asyncio
async def test_import_environments_skip_existing(client: AsyncClient, auth_headers):
    """Importing an environment whose name already exists → skipped, not error."""
    # Pre-create the environment
    await client.post(
        "/api/v1/environments/",
        headers=auth_headers,
        json={"name": "ExistingEnv", "environment_type": "test"},
    )

    file_bytes = make_environment_excel([
        {"Name": "ExistingEnv", "Type": "uat"},
        {"Name": "BrandNewEnv", "Type": "staging"},
    ])

    resp = await client.post(
        "/api/v1/import/environments",
        headers=auth_headers,
        files={"file": ("envs.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_import_environments_missing_required_col(client: AsyncClient, auth_headers):
    """File without Name column → HTTP 400."""
    file_bytes = make_environment_excel_no_name_col([
        {"Type": "uat", "Description": "No name column"},
    ])

    resp = await client.post(
        "/api/v1/import/environments",
        headers=auth_headers,
        files={"file": ("envs.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 400
    assert "Name" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tests — Systems
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_systems(client: AsyncClient, auth_headers):
    """POST /import/systems with a valid file creates new systems."""
    file_bytes = make_system_excel([
        {"Name": "ImportedSystem1", "Description": "First system"},
        {"Name": "ImportedSystem2", "GitHub URL": "https://github.com/example/repo"},
    ])

    resp = await client.post(
        "/api/v1/import/systems",
        headers=auth_headers,
        files={"file": ("systems.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["errors"] == []

    # Verify systems exist via list endpoint
    list_resp = await client.get("/api/v1/systems/", headers=auth_headers)
    names = [s["name"] for s in list_resp.json()]
    assert "ImportedSystem1" in names
    assert "ImportedSystem2" in names


@pytest.mark.asyncio
async def test_import_systems_skip_existing(client: AsyncClient, auth_headers):
    """Importing a system whose name already exists → skipped, not error."""
    # Pre-create the system
    await client.post(
        "/api/v1/systems/",
        headers=auth_headers,
        json={"name": "ExistingSystem"},
    )

    file_bytes = make_system_excel([
        {"Name": "ExistingSystem"},
        {"Name": "FreshSystem"},
    ])

    resp = await client.post(
        "/api/v1/import/systems",
        headers=auth_headers,
        files={"file": ("systems.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 1
    assert data["errors"] == []
