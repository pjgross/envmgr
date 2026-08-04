"""Integration tests for Excel Import (M5)."""
import io

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.services.environment_tier_defaults import (
    seed_environment_tier_defaults_for_tenant,
)
from tests.factories import post_environment


@pytest_asyncio.fixture
async def seeded_tiers(db_session, test_tenant):
    """The tier vocabulary the import resolves against.

    Production tenants get it from tenant_service.create_tenant; the bare
    `test_tenant` fixture is built as a raw row, so it has none.
    """
    await seed_environment_tier_defaults_for_tenant(db_session, test_tenant.id)
    await db_session.commit()


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
async def test_import_environments(client: AsyncClient, auth_headers, seeded_tiers):
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
async def test_import_environments_skip_existing(
    client: AsyncClient, auth_headers, seeded_tiers
):
    """Importing an environment whose name already exists → skipped, not error."""
    # Pre-create the environment
    await post_environment(client, auth_headers, "ExistingEnv")

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
async def test_import_sets_the_importing_admin_as_owner_with_no_expiry(
    client: AsyncClient, auth_headers, seeded_tiers
):
    """The importer is present, acting and identifiable, so recording them as
    owner is truthful — unlike fabricating an owner for a pre-existing row,
    which the spec deliberately refused. `expires_at` stays null: the
    spreadsheet has none to offer, and null now means "no expiry planned"."""
    file_bytes = make_environment_excel([
        {"Name": "ImportedWithOwner", "Type": "uat"},
    ])

    resp = await client.post(
        "/api/v1/import/environments",
        headers=auth_headers,
        files={"file": ("envs.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["created"] == 1

    me = await client.get("/api/v1/auth/me", headers=auth_headers)

    list_resp = await client.get("/api/v1/environments/", headers=auth_headers)
    [env] = [e for e in list_resp.json() if e["name"] == "ImportedWithOwner"]
    assert env["owner_username"] == me.json()["username"]
    assert env["expires_at"] is None


@pytest.mark.asyncio
async def test_an_imported_environment_can_be_patched_without_supplying_an_expiry(
    client: AsyncClient, auth_headers, seeded_tiers
):
    """The defect this fix closes: before Decision 1, a null expiry counted as
    a governance gap and the PATCH compliance rule refused every patch until
    both owner and expiry were supplied — freezing every imported row,
    because the importer sets an owner but deliberately no expiry. A
    description-only patch must now succeed on its own."""
    file_bytes = make_environment_excel([
        {"Name": "ImportedThenPatched", "Type": "uat"},
    ])
    resp = await client.post(
        "/api/v1/import/environments",
        headers=auth_headers,
        files={"file": ("envs.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text

    list_resp = await client.get("/api/v1/environments/", headers=auth_headers)
    [env] = [e for e in list_resp.json() if e["name"] == "ImportedThenPatched"]
    assert env["expires_at"] is None  # imported rows have no expiry, by design

    patched = await client.patch(
        f"/api/v1/environments/{env['id']}",
        headers=auth_headers,
        json={"description": "reviewed, still no expiry planned"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["expires_at"] is None


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
