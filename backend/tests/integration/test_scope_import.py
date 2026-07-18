"""Integration tests for the scope spreadsheet-import endpoint."""
from io import BytesIO

import openpyxl
import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release


@pytest_asyncio.fixture
async def scope_release(db_session, test_tenant, test_user):
    tpl = LifecycleTemplate(
        tenant_id=test_tenant.id, entity_type="release", name="Major", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=test_tenant.id, name="R1", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=test_user.id,
    )
    db_session.add(r)
    await db_session.commit()
    await db_session.refresh(r)
    return r


def _xlsx() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["external_key", "title", "description", "change_kind",
               "external_status", "project_code", "project_name"])
    ws.append(["PAY-1", "Login", "d", "story", "New", "PAY", "Payments"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_happy_path(client: AsyncClient, auth_headers, scope_release):
    resp = await client.post(
        f"/api/v1/releases/{scope_release.id}/scope/import",
        headers=auth_headers,
        files={"file": ("scope.xlsx", _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1
    assert body["updated"] == 0


@pytest.mark.asyncio
async def test_import_unauthenticated(client: AsyncClient, scope_release):
    resp = await client.post(
        f"/api/v1/releases/{scope_release.id}/scope/import",
        files={"file": ("scope.xlsx", _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_import_rejects_unknown_release(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v1/releases/999999/scope/import",
        headers=auth_headers,
        files={"file": ("scope.xlsx", _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 404
