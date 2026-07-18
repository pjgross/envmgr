# Scope Items (SP-1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make release scope items (`ReleaseChange`) PM-useful now, independent of the deferred Jira importer — add a first-class project code + name, and allow manual entry + spreadsheet import.

**Architecture:** Extend the existing `ReleaseChange` model + `release_scope_service` with two nullable columns and an `openpyxl`-based import service mirroring `excel_import_service`. Backend is TDD (pytest/SQLite). Frontend follows the project's build-and-manually-verify convention (no FE unit-test harness).

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, openpyxl, pytest; React 18 + TS + MUI + Redux Toolkit.

This is SP-1 of the RAID feature ([spec](../specs/2026-07-18-release-raid-and-scope-items-design.md) §2). SP-2 (RAID Log) is a separate plan that builds on this.

---

## File structure

- Modify `backend/app/db/models/release_change.py` — add `project_code`, `project_name`.
- Create `backend/app/db/migrations/versions/20260718_1200_scopeprojfields_project_code_name.py` — add the two columns (Postgres; SQLite tests get them via `create_all`).
- Modify `backend/app/api/v1/schemas/release_change.py` — add the fields to Create/Update/Read; add `ScopeImportResult`.
- Modify `backend/app/services/release_scope_service.py` — persist the fields in `create_change`.
- Create `backend/app/services/scope_import_service.py` — spreadsheet parser + upsert.
- Modify `backend/app/api/v1/releases.py` — import endpoint + template download.
- Test `backend/tests/services/test_release_scope_service.py` (extend), `backend/tests/services/test_scope_import_service.py` (new), `backend/tests/integration/test_scope_import.py` (new).
- Frontend: `frontend/src/components/releases/ScopeItemDialog.tsx`, `ScopeTable.tsx`, `ReleaseScopeTab.tsx`, new `ScopeImportDialog.tsx`, and the scope API service/type used by these.

---

## Task 1: Add `project_code` / `project_name` columns

**Files:**
- Modify: `backend/app/db/models/release_change.py`
- Create: `backend/app/db/migrations/versions/20260718_1200_scopeprojfields_project_code_name.py`

- [ ] **Step 1: Add columns to the model**

In `release_change.py`, after the `system_id` column add:

```python
    project_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
```

- [ ] **Step 2: Write the migration**

```python
"""scope items: add project_code + project_name to release_change

Revision ID: scopeprojfields
Revises: nameuniqguard
Create Date: 2026-07-18 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "scopeprojfields"
down_revision: Union[str, None] = "nameuniqguard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "release_change", "project_code"):
        op.add_column("release_change", sa.Column("project_code", sa.String(50), nullable=True))
        op.create_index("ix_release_change_project_code", "release_change", ["project_code"])
    if not _column_exists(conn, "release_change", "project_name"):
        op.add_column("release_change", sa.Column("project_name", sa.String(200), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "release_change", "project_name"):
        op.drop_column("release_change", "project_name")
    if _column_exists(conn, "release_change", "project_code"):
        try:
            op.drop_index("ix_release_change_project_code", table_name="release_change")
        except Exception:
            pass
        op.drop_column("release_change", "project_code")
```

- [ ] **Step 3: Verify the migration chains**

Run: `cd backend && uv run alembic heads`
Expected: `scopeprojfields (head)`

- [ ] **Step 4: Commit**

```bash
git add backend/app/db/models/release_change.py backend/app/db/migrations/versions/20260718_1200_scopeprojfields_project_code_name.py
git commit -m "feat(scope): add project_code + project_name to release_change"
```

---

## Task 2: Schemas — expose the fields + import result

**Files:**
- Modify: `backend/app/api/v1/schemas/release_change.py`

- [ ] **Step 1: Add fields to Create/Update/Read and a result schema**

Add `project_code` / `project_name` to `ReleaseChangeCreate`:

```python
    project_code: Optional[str] = Field(None, max_length=50)
    project_name: Optional[str] = Field(None, max_length=200)
```

Add the same two lines to `ReleaseChangeUpdate` (its `setattr` loop persists them automatically) and to `ReleaseChangeRead`:

```python
    project_code: Optional[str] = None
    project_name: Optional[str] = None
```

At the bottom of the file add the import-result schema:

```python
from app.api.v1.schemas.version import ImportError  # noqa: E402


class ScopeImportResult(BaseModel):
    created: int
    updated: int
    errors: list[ImportError]
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/v1/schemas/release_change.py
git commit -m "feat(scope): schema fields for project_code/name + ScopeImportResult"
```

---

## Task 3: Service persists the project fields (TDD)

**Files:**
- Modify: `backend/app/services/release_scope_service.py`
- Test: `backend/tests/services/test_release_scope_service.py`

- [ ] **Step 1: Write the failing test**

Append to `test_release_scope_service.py`:

```python
@pytest.mark.asyncio
async def test_create_change_persists_project_fields(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(
            title="Login", change_kind="story",
            project_code="PAY", project_name="Payments Platform",
        ),
        tenant.id, user.id,
    )
    assert change.project_code == "PAY"
    assert change.project_name == "Payments Platform"


@pytest.mark.asyncio
async def test_update_change_edits_project_fields(db_session, tenant, user):
    release = await _make_release(db_session, tenant.id, user.id)
    change = await release_scope_service.create_change(
        db_session, release.id,
        ReleaseChangeCreate(title="X", change_kind="story"),
        tenant.id, user.id,
    )
    updated = await release_scope_service.update_change(
        db_session, change.id,
        ReleaseChangeUpdate(project_code="RET", project_name="Retail"),
        tenant.id, user.id,
    )
    assert updated.project_code == "RET"
    assert updated.project_name == "Retail"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_release_scope_service.py::test_create_change_persists_project_fields -v`
Expected: FAIL — `AttributeError`/`TypeError` (create_change doesn't set the columns yet).

- [ ] **Step 3: Persist the fields in `create_change`**

In `release_scope_service.create_change`, in the `ReleaseChange(...)` constructor, add:

```python
        project_code=data.project_code,
        project_name=data.project_name,
```

(`update_change` already applies them via its `model_dump(exclude_unset=True)` → `setattr` loop, so no change is needed there.)

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_release_scope_service.py -k project -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/release_scope_service.py backend/tests/services/test_release_scope_service.py
git commit -m "feat(scope): persist project_code/name on create + update"
```

---

## Task 4: Spreadsheet import service (TDD)

**Files:**
- Create: `backend/app/services/scope_import_service.py`
- Test: `backend/tests/services/test_scope_import_service.py`

- [ ] **Step 1: Write the failing tests**

Create `test_scope_import_service.py`:

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/services/test_scope_import_service.py -v`
Expected: FAIL — `ModuleNotFoundError: scope_import_service`.

- [ ] **Step 3: Implement the service**

Create `scope_import_service.py`:

```python
"""Scope import service — imports release scope items (ReleaseChange) from .xlsx.

Upserts on (release_id, external_key) when an external_key is present; otherwise
inserts. Sets source='spreadsheet'. No per-row events (bulk import).
"""
from io import BytesIO
from typing import Optional

import openpyxl
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.version import ImportError
from app.db.models.release_change import ReleaseChange

_COLUMNS = ["external_key", "title", "description", "change_kind",
            "external_status", "project_code", "project_name"]


def _header_index(headers: list, name: str, required: bool) -> Optional[int]:
    lower = name.lower()
    for i, h in enumerate(headers):
        if h is not None and str(h).strip().lower() == lower:
            return i
    if required:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing required column: '{name}'")
    return None


def _cell(row: tuple, idx: Optional[int]) -> Optional[str]:
    if idx is None or idx >= len(row):
        return None
    v = row[idx]
    if v is None:
        return None
    s = str(v).strip()
    return s or None


async def import_scope(
    db: AsyncSession, file_bytes: bytes, release_id: int, tenant_id: int
) -> dict:
    try:
        wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Could not read spreadsheet")
    ws = wb.active
    headers = [c.value for c in ws[1]]
    idx = {c: _header_index(headers, c, required=(c in ("title", "change_kind"))) for c in _COLUMNS}

    created = updated = 0
    errors: list[ImportError] = []

    for rownum, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if row is None or all(v is None for v in row):
            continue
        title = _cell(row, idx["title"])
        kind = _cell(row, idx["change_kind"])
        if not title:
            errors.append(ImportError(row=rownum, field="title", message="title is required"))
            continue
        if not kind:
            errors.append(ImportError(row=rownum, field="change_kind", message="change_kind is required"))
            continue
        ek = _cell(row, idx["external_key"])

        existing = None
        if ek:
            existing = (await db.execute(
                select(ReleaseChange).where(
                    ReleaseChange.tenant_id == tenant_id,
                    ReleaseChange.release_id == release_id,
                    ReleaseChange.external_key == ek,
                    ReleaseChange.deleted_at.is_(None),
                )
            )).scalar_one_or_none()

        fields = dict(
            title=title, change_kind=kind,
            description=_cell(row, idx["description"]),
            external_status=_cell(row, idx["external_status"]),
            project_code=_cell(row, idx["project_code"]),
            project_name=_cell(row, idx["project_name"]),
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            existing.source = "spreadsheet"
            updated += 1
        else:
            db.add(ReleaseChange(
                tenant_id=tenant_id, release_id=release_id, external_key=ek,
                source="spreadsheet", **fields,
            ))
            created += 1

    await db.flush()
    return {"created": created, "updated": updated, "errors": errors}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/services/test_scope_import_service.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/scope_import_service.py backend/tests/services/test_scope_import_service.py
git commit -m "feat(scope): spreadsheet import service with external_key upsert"
```

---

## Task 5: Import + template endpoints

**Files:**
- Modify: `backend/app/api/v1/releases.py`

- [ ] **Step 1: Add the endpoints**

Near the scope endpoints (after `create_change`, ~releases.py:878), add. `_require_release` already validates the release belongs to the tenant (tenant isolation):

```python
@router.post("/{release_id}/scope/import", response_model=ScopeImportResult)
async def import_scope(
    release_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    from app.services import scope_import_service
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    file_bytes = await file.read()
    return await scope_import_service.import_scope(db, file_bytes, release_id, tenant_id)


@router.get("/scope/import-template")
async def scope_import_template(current_user=Depends(get_current_user)):
    import openpyxl
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["external_key", "title", "description", "change_kind",
               "external_status", "project_code", "project_name"])
    ws.append(["PAY-1", "Example story", "Optional description", "story",
               "In Progress", "PAY", "Payments Platform"])
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=scope_import_template.xlsx"},
    )
```

- [ ] **Step 2: Ensure imports exist at the top of `releases.py`**

Confirm `UploadFile`, `File` are imported from `fastapi` (add to the existing `from fastapi import ...` line if missing), `require_tenant_admin` from `app.core.security`, and add `ScopeImportResult` to the `from app.api.v1.schemas.release_change import (...)` block.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/v1/releases.py
git commit -m "feat(scope): import + template-download endpoints"
```

---

## Task 6: Integration tests for the import endpoint

**Files:**
- Test: `backend/tests/integration/test_scope_import.py`

- [ ] **Step 1: Write the tests**

Create `test_scope_import.py`:

```python
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
```

- [ ] **Step 2: Run to verify they pass**

Run: `cd backend && uv run pytest tests/integration/test_scope_import.py -v`
Expected: PASS (3 tests). If `auth_headers`/`test_tenant`/`test_user` fixtures differ, align with `tests/conftest.py`.

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: all pass (previous count + the new scope tests).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_scope_import.py
git commit -m "test(scope): integration tests for scope import endpoint"
```

---

## Task 7: Frontend — project fields + import dialog

**Files:**
- Modify: `frontend/src/components/releases/ScopeItemDialog.tsx`
- Modify: `frontend/src/components/releases/ScopeTable.tsx`
- Modify: `frontend/src/components/releases/ReleaseScopeTab.tsx`
- Create: `frontend/src/components/releases/ScopeImportDialog.tsx`
- Modify: the scope API service + `ReleaseChange` TS type used by the above (add `project_code`, `project_name`).

> No FE unit-test harness in this project — these are build-and-verify tasks.

- [ ] **Step 1: Type + service**

Add `project_code?: string | null` and `project_name?: string | null` to the `ReleaseChange` TypeScript type, and include them in the create/update request bodies the scope service sends. Add two service calls: `importScope(releaseId, file)` → `POST /releases/{id}/scope/import` (multipart), and a template-download link to `GET /releases/scope/import-template`.

- [ ] **Step 2: ScopeItemDialog fields**

Add two MUI `TextField`s — "Project code" (maxLength 50) and "Project name" (maxLength 200) — wired to the dialog's form state and submitted in the create/update payload.

- [ ] **Step 3: ScopeTable columns + group**

Add `project_code` and `project_name` columns; add a "group/filter by project" control (filter the rows by `project_code`).

- [ ] **Step 4: ScopeImportDialog**

Create a dialog with: a template-download link, a file picker (`.xlsx`), a submit that calls `importScope`, and a result summary (created / updated / per-row errors). Add an "Import from spreadsheet" button to `ReleaseScopeTab` that opens it and refreshes the scope list on success.

- [ ] **Step 5: Verify in the running app**

Run frontend + backend (`docker-compose up -d`, `uvicorn app.main:app --reload`, `npm run dev`), log in as `admin`/`admin123` (tenant `demo`), open a release's Scope tab, create a scope item with a project code/name, and import the template file. Confirm rows appear with project columns and re-importing the same `external_key` updates rather than duplicates.

- [ ] **Step 6: Lint + commit**

```bash
cd frontend && npm run lint
git add frontend/src/components/releases/ frontend/src/services frontend/src/types frontend/src/store
git commit -m "feat(scope): project code/name fields + spreadsheet import UI"
```

---

## Task 8: Docs

**Files:**
- Modify: `docs/user-guide.md` (scope chapter) and/or `docs/admin-guide.md`

- [ ] **Step 1: Document project code/name + spreadsheet import**

Add a short subsection to the scope/release chapter: the new project code/name fields, how to download the template, the column meanings, and the `external_key` upsert behaviour.

- [ ] **Step 2: Commit**

```bash
git add docs/user-guide.md docs/admin-guide.md
git commit -m "docs(scope): project code/name + spreadsheet import"
```

---

## Self-review notes
- **Spec coverage (§2):** project_code/name (Task 1–3), source stays VARCHAR so `spreadsheet` needs no enum migration — the import service sets `source="spreadsheet"` directly (Task 4); spreadsheet import + template (Task 4–5); UI (Task 7); tests (Task 3/4/6). Jira/GitLab/GitHub importers remain deferred (not in this plan).
- **Upsert semantics:** `(release_id, external_key)` when `external_key` present; blank-key rows always insert — explicit in Task 4 tests.
- **Tenant isolation:** endpoint uses `active_tenant_id` + `_require_release`; the service filters every query by `tenant_id` + `release_id`.
