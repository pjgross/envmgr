"""Tests for scope_import_service — spreadsheet import of release scope items."""
from io import BytesIO

import openpyxl
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.release_change import ReleaseChange
from app.services import scope_import_service


async def _make_release(db_session, tenant_id, user_id):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="Major", is_default=True,
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    r = Release(
        tenant_id=tenant_id, name="R1", release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
    )
    db_session.add(r)
    await db_session.flush()
    return r


def _xlsx(rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["external_key", "title", "description", "change_kind",
               "external_status", "project_code", "project_name"])
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_import_creates_scope_items(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    data = _xlsx([
        ["PAY-1", "Login flow", "desc", "story", "In Progress", "PAY", "Payments"],
        [None, "Ad-hoc item", None, "defect", None, "RET", "Retail"],
    ])
    result = await scope_import_service.import_scope(db_session, data, release.id, tenant.id)
    assert result["created"] == 2
    assert result["updated"] == 0
    assert result["errors"] == []
    rows = (await db_session.execute(
        select(ReleaseChange).where(ReleaseChange.release_id == release.id)
    )).scalars().all()
    assert {r.project_code for r in rows} == {"PAY", "RET"}
    assert all(r.source == "spreadsheet" for r in rows)


@pytest.mark.asyncio
async def test_import_upserts_on_external_key(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    await scope_import_service.import_scope(
        db_session, _xlsx([["PAY-1", "Old title", None, "story", None, "PAY", "Payments"]]),
        release.id, tenant.id,
    )
    result = await scope_import_service.import_scope(
        db_session, _xlsx([["PAY-1", "New title", None, "story", None, "PAY", "Payments"]]),
        release.id, tenant.id,
    )
    assert result["created"] == 0
    assert result["updated"] == 1
    rows = (await db_session.execute(
        select(ReleaseChange).where(ReleaseChange.release_id == release.id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "New title"


@pytest.mark.asyncio
async def test_import_reports_row_errors(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    data = _xlsx([
        [None, None, None, "story", None, None, None],       # missing title
        [None, "No kind", None, None, None, None, None],     # missing change_kind
    ])
    result = await scope_import_service.import_scope(db_session, data, release.id, tenant.id)
    assert result["created"] == 0
    assert {e.field for e in result["errors"]} == {"title", "change_kind"}
