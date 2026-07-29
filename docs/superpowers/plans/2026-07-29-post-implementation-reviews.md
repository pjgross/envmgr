# Post-Implementation Reviews (Phase 5 SP4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, release-scoped Post-Implementation Review (PIR) record (optionally linked to an incident), with CRUD via the release, surfaced on the release detail page, the incident detail page (finishing the SP1-deferred panel), and a PIR-status column on the incident list.

**Architecture:** A new `PIR` model (one per release, `release_id` unique) + a tenant-scoped `pir_service` + thin `/api/v1/releases/{id}/pir` CRUD. Incident integration adds a `pir` field to the incident detail and a `pir_status` to incident list rows (bulk-looked-up). Frontend follows existing tab/panel patterns; no Redux slice needed for the PIR itself.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic + pytest; React 18 + TS strict + MUI; vitest.

**Spec:** `docs/superpowers/specs/2026-07-29-post-implementation-reviews-design.md`

---

## Reference facts (verified)

- `Release` (`release`) is the PIR owner; `Incident` (`incident`, SP1) is the optional link. Both have `tenant_id` + `deleted_at`.
- `incident_service.get_incident_detail` (`app/services/incident_service.py:205`) returns a **dict** ending with `allowed_transitions`/`status_history` (`:229-253`) — add a `"pir"` key here.
- The incident list-row builder is `_row(db, inc, tenant_id)` in `app/api/v1/incidents.py:16` returning `IncidentListRow(...)` — add `pir_status`.
- Incident schemas: `IncidentDetail` (`app/api/v1/schemas/incident.py:103`) and `IncidentListRow` (`:86`) — add `pir` / `pir_status`.
- `ReleaseDetail.tsx` has 9 tabs (indices 0–8: Main/Gates/Systems/Environments/Linked Requests/Scope/RAID/Enterprise/Deployments). Add **PIR at index 9** (append — no reindex of existing panels).
- Conventions: manual Alembic DDL (`op.create_table`); `alembic upgrade head` may hit DuplicateTable from `init_db` create_all → `alembic stamp` (known quirk); `db.flush()` not commit; every query filters `tenant_id` + `deleted_at IS NULL`; validate FK ownership (IDOR).
- Backend cmds from `backend/` (`uv run pytest`); frontend from `frontend/` (`npx`).

---

## File Structure

**Backend — create:** `app/db/models/pir.py`, `app/api/v1/schemas/pir.py`, `app/services/pir_service.py`, `app/api/v1/pir.py`, `alembic/versions/<rev>_pir.py`, tests `tests/services/test_pir_service.py`, `tests/integration/test_pir_api.py`.
**Backend — modify:** `app/db/models/__init__.py`, `app/main.py`, `app/services/incident_service.py`, `app/api/v1/incidents.py`, `app/api/v1/schemas/incident.py`.
**Frontend — create:** `src/types/pir.ts`, `src/services/pirService.ts`, `src/components/releases/ReleasePirTab.tsx`.
**Frontend — modify:** `src/pages/releases/ReleaseDetail.tsx`, `src/pages/incidents/IncidentDetail.tsx`, `src/pages/incidents/IncidentList.tsx`, `src/types/incident.ts`.

---

## Task 1: `PIR` model + migration

**Files:** Create `backend/app/db/models/pir.py`; Modify `backend/app/db/models/__init__.py`; Create migration.

- [ ] **Step 1: Model** — `backend/app/db/models/pir.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PIR(Base):
    __tablename__ = "pir"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("release.id"), nullable=False, index=True)
    incident_id: Mapped[Optional[int]] = mapped_column(ForeignKey("incident.id"), nullable=True, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_went_well: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    what_went_wrong: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_plan: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="draft")  # draft | complete
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_tenant_release", "tenant_id", "release_id"),
        Index("ix_pir_tenant_incident", "tenant_id", "incident_id"),
    )
```

(One PIR per release is enforced in the service — no DB unique constraint, so a soft-deleted PIR doesn't block a new one.)

- [ ] **Step 2: Register** in `app/db/models/__init__.py` (match existing style): `from app.db.models.pir import PIR  # noqa: F401` (+ `"PIR"` in `__all__`).

- [ ] **Step 3: Migration** — `alembic revision -m "pir"`, manual DDL:

```python
def upgrade() -> None:
    op.create_table(
        "pir",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("release_id", sa.Integer(), sa.ForeignKey("release.id"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id"), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("what_went_well", sa.Text(), nullable=True),
        sa.Column("what_went_wrong", sa.Text(), nullable=True),
        sa.Column("action_plan", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="draft"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pir_tenant_id", "pir", ["tenant_id"])
    op.create_index("ix_pir_release_id", "pir", ["release_id"])
    op.create_index("ix_pir_incident_id", "pir", ["incident_id"])
    op.create_index("ix_pir_tenant_release", "pir", ["tenant_id", "release_id"])
    op.create_index("ix_pir_tenant_incident", "pir", ["tenant_id", "incident_id"])


def downgrade() -> None:
    op.drop_table("pir")
```

- [ ] **Step 4:** `alembic upgrade head` (or `alembic stamp <rev>` if DuplicateTable); `uv run python -c "from app.db.models import PIR; print('ok')"` → `ok`.
- [ ] **Step 5: Commit** `git add backend/app/db/models/pir.py backend/app/db/models/__init__.py backend/alembic/versions/ && git commit -m "feat(pir): PIR model & migration (Phase 5 SP4)"`

---

## Task 2: Schemas (PIR + incident additions)

**Files:** Create `backend/app/api/v1/schemas/pir.py`; Modify `backend/app/api/v1/schemas/incident.py`.

- [ ] **Step 1: PIR schemas** — `backend/app/api/v1/schemas/pir.py`:

```python
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, field_validator

PIR_STATUSES = {"draft", "complete"}


class PIRCreate(BaseModel):
    incident_id: Optional[int] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    what_went_well: Optional[str] = None
    what_went_wrong: Optional[str] = None
    action_plan: Optional[str] = None
    status: Optional[str] = "draft"

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRUpdate(BaseModel):
    incident_id: Optional[int] = None
    summary: Optional[str] = None
    root_cause: Optional[str] = None
    what_went_well: Optional[str] = None
    what_went_wrong: Optional[str] = None
    action_plan: Optional[str] = None
    status: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _st(cls, v):
        if v is not None and v not in PIR_STATUSES:
            raise ValueError(f"status must be one of {sorted(PIR_STATUSES)}")
        return v


class PIRResponse(BaseModel):
    id: int
    release_id: int
    incident_id: Optional[int]
    summary: Optional[str]
    root_cause: Optional[str]
    what_went_well: Optional[str]
    what_went_wrong: Optional[str]
    action_plan: Optional[str]
    status: str
    completed_at: Optional[datetime]
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 2: Incident schema additions** — in `backend/app/api/v1/schemas/incident.py`, add a small `IncidentPirRef` and wire it in:

```python
class IncidentPirRef(BaseModel):
    release_id: int
    status: str
    root_cause: Optional[str] = None
    action_plan: Optional[str] = None
    summary: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)
```

Add to `IncidentListRow`: `pir_status: str = "none"`  (values: `complete`|`draft`|`none`).
Add to `IncidentDetail`: `pir: Optional[IncidentPirRef] = None`.

- [ ] **Step 3:** `uv run python -c "import app.api.v1.schemas.pir, app.api.v1.schemas.incident; print('ok')"` → `ok`; commit `git commit -am "feat(pir): schemas + incident pir fields (Phase 5 SP4)"` (after `git add` the two files).

---

## Task 3: `pir_service` (TDD)

**Files:** Create `backend/app/services/pir_service.py`; Test `backend/tests/services/test_pir_service.py`.

- [ ] **Step 1: Failing tests** — build a release (and, where needed, an incident) via the models the way sibling tests do (check `tests/services/test_dora_service.py` for a `Release`/`Incident` construction pattern — Release needs `name, release_type, raised_by (user), lifecycle_template_id, status`; a lifecycle template + user come from the `user` fixture + a looked-up/created `LifecycleTemplate`). Tests:

```python
import pytest
from fastapi import HTTPException
from app.services import pir_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate
# ... (helpers to make a Release `rel` and an Incident `inc` for `tenant`/`user` — mirror test_dora_service.py) ...


@pytest.mark.asyncio
async def test_create_and_get_for_release(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    pir = await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(summary="s"), user.id)
    assert pir.status == "draft"
    got = await pir_service.get_for_release(db_session, tenant.id, rel.id)
    assert got.id == pir.id


@pytest.mark.asyncio
async def test_duplicate_create_409(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    with pytest.raises(HTTPException) as e:
        await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    assert e.value.status_code == 409


@pytest.mark.asyncio
async def test_create_unknown_release_404(db_session, tenant, user):
    with pytest.raises(HTTPException) as e:
        await pir_service.create_for_release(db_session, tenant.id, 999999, PIRCreate(), user.id)
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_complete_sets_and_clears_completed_at(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    p = await pir_service.update(db_session, tenant.id, rel.id, PIRUpdate(status="complete"))
    assert p.completed_at is not None
    p = await pir_service.update(db_session, tenant.id, rel.id, PIRUpdate(status="draft"))
    assert p.completed_at is None


@pytest.mark.asyncio
async def test_soft_delete_allows_recreate(db_session, tenant, user, rel_factory):
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    await pir_service.delete(db_session, tenant.id, rel.id)
    assert await pir_service.get_for_release(db_session, tenant.id, rel.id) is None
    # recreate must succeed (soft-deleted one doesn't block)
    again = await pir_service.create_for_release(db_session, tenant.id, rel.id, PIRCreate(), user.id)
    assert again.id is not None


@pytest.mark.asyncio
async def test_pir_status_for_incidents_bulk(db_session, tenant, user, rel_factory, incident_factory):
    inc = await incident_factory()
    rel = await rel_factory()
    await pir_service.create_for_release(db_session, tenant.id, rel.id,
                                         PIRCreate(incident_id=inc.id, status="complete"), user.id)
    m = await pir_service.pir_status_for_incidents(db_session, tenant.id, [inc.id, 999999])
    assert m.get(inc.id) == "complete" and 999999 not in m
```

Provide `rel_factory`/`incident_factory` inline (or as local fixtures) mirroring how `test_dora_service.py`/`test_incident_service.py` build these rows. Keep assertions as above.

- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3: Implement** — `backend/app/services/pir_service.py`:

```python
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pir import PIR
from app.db.models.release import Release
from app.db.models.incident import Incident


async def _validate_release(db, tenant_id, release_id):
    r = (await db.execute(select(Release).where(
        Release.id == release_id, Release.tenant_id == tenant_id, Release.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if r is None:
        raise HTTPException(status_code=404, detail="Release not found")


async def _validate_incident(db, tenant_id, incident_id):
    if incident_id is None:
        return
    i = (await db.execute(select(Incident).where(
        Incident.id == incident_id, Incident.tenant_id == tenant_id, Incident.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if i is None:
        raise HTTPException(status_code=422, detail="incident_id does not reference a valid incident for this tenant")


async def get_for_release(db: AsyncSession, tenant_id: int, release_id: int) -> Optional[PIR]:
    return (await db.execute(select(PIR).where(
        PIR.release_id == release_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def get_for_incident(db: AsyncSession, tenant_id: int, incident_id: int) -> Optional[PIR]:
    return (await db.execute(select(PIR).where(
        PIR.incident_id == incident_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()


async def create_for_release(db: AsyncSession, tenant_id: int, release_id: int, data, user_id: int) -> PIR:
    await _validate_release(db, tenant_id, release_id)
    if await get_for_release(db, tenant_id, release_id) is not None:
        raise HTTPException(status_code=409, detail="A PIR already exists for this release")
    await _validate_incident(db, tenant_id, data.incident_id)
    pir = PIR(
        tenant_id=tenant_id, release_id=release_id, incident_id=data.incident_id,
        summary=data.summary, root_cause=data.root_cause, what_went_well=data.what_went_well,
        what_went_wrong=data.what_went_wrong, action_plan=data.action_plan,
        status=data.status or "draft", created_by=user_id,
    )
    if pir.status == "complete":
        pir.completed_at = datetime.now(timezone.utc)
    db.add(pir)
    await db.flush()
    return pir


async def update(db: AsyncSession, tenant_id: int, release_id: int, data) -> PIR:
    pir = await get_for_release(db, tenant_id, release_id)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    payload = data.model_dump(exclude_unset=True)
    if "incident_id" in payload:
        await _validate_incident(db, tenant_id, payload["incident_id"])
    for k, v in payload.items():
        setattr(pir, k, v)
    if pir.status == "complete" and pir.completed_at is None:
        pir.completed_at = datetime.now(timezone.utc)
    if pir.status != "complete":
        pir.completed_at = None
    await db.flush()
    return pir


async def delete(db: AsyncSession, tenant_id: int, release_id: int) -> None:
    pir = await get_for_release(db, tenant_id, release_id)
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    pir.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def pir_status_for_incidents(db: AsyncSession, tenant_id: int, incident_ids) -> dict[int, str]:
    ids = [i for i in incident_ids if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(select(PIR.incident_id, PIR.status).where(
        PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None), PIR.incident_id.in_(ids),
    ))).all()
    return {iid: st for iid, st in rows}
```

- [ ] **Step 4:** run → PASS. **Step 5:** commit `feat(pir): pir_service CRUD + status lookups (Phase 5 SP4)`.

---

## Task 4: PIR API router + mount (TDD)

**Files:** Create `backend/app/api/v1/pir.py`; Modify `backend/app/main.py`; Test `backend/tests/integration/test_pir_api.py`.

- [ ] **Step 1: Failing integration tests** (mirror the `authed_client` + release-creation fixture from existing integration tests; a release can be created via `releaseService`/the releases API or the model):

```python
import pytest


@pytest.mark.asyncio
async def test_pir_crud_flow(authed_client, demo_release_id):
    # none yet
    assert (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).status_code in (200, 204)
    # create
    r = await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir",
                                 json={"summary": "went ok", "root_cause": "n/a"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "draft"
    # duplicate -> 409
    assert (await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={})).status_code == 409
    # complete
    r = await authed_client.patch(f"/api/v1/releases/{demo_release_id}/pir", json={"status": "complete"})
    assert r.status_code == 200 and r.json()["status"] == "complete"
    # delete
    assert (await authed_client.delete(f"/api/v1/releases/{demo_release_id}/pir")).status_code == 204
```

Build `demo_release_id` mirroring how other integration tests create a release in the test tenant.

- [ ] **Step 2:** run → FAIL (404). **Step 3: Router** — `backend/app/api/v1/pir.py`:

```python
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user
from app.services import pir_service
from app.api.v1.schemas.pir import PIRCreate, PIRUpdate, PIRResponse

router = APIRouter(prefix="/releases", tags=["pir"])


@router.get("/{release_id}/pir", response_model=PIRResponse | None)
async def get_pir(release_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await pir_service.get_for_release(db, current_user.active_tenant_id, release_id)


@router.post("/{release_id}/pir", response_model=PIRResponse, status_code=status.HTTP_201_CREATED)
async def create_pir(release_id: int, data: PIRCreate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await pir_service.create_for_release(db, current_user.active_tenant_id, release_id, data, current_user.id)


@router.patch("/{release_id}/pir", response_model=PIRResponse)
async def update_pir(release_id: int, data: PIRUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    return await pir_service.update(db, current_user.active_tenant_id, release_id, data)


@router.delete("/{release_id}/pir", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pir(release_id: int, db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    await pir_service.delete(db, current_user.active_tenant_id, release_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Mount** — in `app/main.py`, next to the other v1 mounts: `from app.api.v1 import pir as pir_router` / `app.include_router(pir_router.router, prefix="/api/v1")`. **Route-order note:** other `/releases/...` routes exist; a specific `/releases/{release_id}/pir` literal won't collide with `/releases/{id}`-style routes, but mount it and confirm the tests pass (if a collision appears, mount before the releases router).
- [ ] **Step 5:** run → PASS. **Step 6:** commit `feat(pir): releases/{id}/pir CRUD API (Phase 5 SP4)`.

---

## Task 5: Incident integration — `pir` on detail + `pir_status` on list (TDD)

**Files:** Modify `backend/app/services/incident_service.py`, `backend/app/api/v1/incidents.py`; Test: append to `backend/tests/integration/test_incidents_api.py` (or the service test).

- [ ] **Step 1: Failing test** (append to incident API tests):

```python
@pytest.mark.asyncio
async def test_incident_detail_includes_pir_and_list_status(authed_client, demo_release_id):
    iid = (await authed_client.post("/api/v1/incidents", json={"title": "x", "severity": "P1"})).json()["id"]
    # create a PIR on the release linked to this incident
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir",
                             json={"incident_id": iid, "status": "complete", "root_cause": "rc"})
    detail = (await authed_client.get(f"/api/v1/incidents/{iid}")).json()
    assert detail["pir"] is not None and detail["pir"]["status"] == "complete" and detail["pir"]["release_id"] == demo_release_id
    rows = (await authed_client.get("/api/v1/incidents")).json()
    assert next(r for r in rows if r["id"] == iid)["pir_status"] == "complete"
```

- [ ] **Step 2:** run → FAIL (`pir` missing / `pir_status` == "none").
- [ ] **Step 3a: detail** — in `incident_service.get_incident_detail`, add to the returned dict (import `from app.services import pir_service` at top; add a `pir` key before the closing `}`):

```python
    pir = await pir_service.get_for_incident(db, tenant_id, inc.id)
    # ... in the returned dict:
    "pir": ({"release_id": pir.release_id, "status": pir.status, "root_cause": pir.root_cause,
             "action_plan": pir.action_plan, "summary": pir.summary} if pir else None),
```

- [ ] **Step 3b: list** — in `app/api/v1/incidents.py`, update `list_incidents` (the endpoint) to bulk-fetch statuses and pass to `_row`. Change `_row` to accept a `pir_status` and set it on the `IncidentListRow`:

```python
# in the list endpoint, after fetching `rows`:
from app.services import pir_service
status_map = await pir_service.pir_status_for_incidents(db, current_user.active_tenant_id, [r.id for r in rows])
return [await _row(db, r, current_user.active_tenant_id, status_map.get(r.id, "none")) for r in rows]

# _row signature + body:
async def _row(db, inc, tenant_id, pir_status: str = "none") -> IncidentListRow:
    ...
    return IncidentListRow(..., pir_status=pir_status)
```

(NOTE: the incident list keys `pir_status` by `incident.id`; PIRs link via `incident_id`, so `status_map` is keyed by incident id — correct.)

- [ ] **Step 4:** run → PASS; also run `uv run pytest tests/services/test_incident_service.py tests/integration/test_incidents_api.py -q` (no regressions). **Step 5:** commit `feat(pir): surface pir on incident detail + pir_status on list (Phase 5 SP4)`.

---

## Task 6: Frontend types + service

**Files:** Create `frontend/src/types/pir.ts`, `frontend/src/services/pirService.ts`; Modify `frontend/src/types/incident.ts`.

- [ ] **Step 1: Types** — `frontend/src/types/pir.ts`:

```ts
export type PirStatus = 'draft' | 'complete';
export interface PIR {
  id: number; release_id: number; incident_id: number | null;
  summary: string | null; root_cause: string | null;
  what_went_well: string | null; what_went_wrong: string | null; action_plan: string | null;
  status: PirStatus; completed_at: string | null;
}
export interface PIRWrite {
  incident_id?: number | null; summary?: string | null; root_cause?: string | null;
  what_went_well?: string | null; what_went_wrong?: string | null; action_plan?: string | null;
  status?: PirStatus;
}
```

- [ ] **Step 2: Service** — `frontend/src/services/pirService.ts` (`import api from './api'`):

```ts
import api from './api';
import type { PIR, PIRWrite } from '../types/pir';

export const pirService = {
  getForRelease: (releaseId: number) =>
    api.get<PIR | null>(`/releases/${releaseId}/pir`).then((r) => r.data),
  create: (releaseId: number, data: PIRWrite) =>
    api.post<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  update: (releaseId: number, data: PIRWrite) =>
    api.patch<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  remove: (releaseId: number) => api.delete(`/releases/${releaseId}/pir`).then((r) => r.data),
};
```

- [ ] **Step 3: Incident type additions** — in `frontend/src/types/incident.ts`: add `pir_status: 'complete' | 'draft' | 'none'` to `IncidentListRow`; add `pir: { release_id: number; status: string; root_cause: string | null; action_plan: string | null; summary: string | null } | null` to `IncidentDetail`.
- [ ] **Step 4:** `npx tsc --noEmit` → PASS; commit `feat(pir): frontend types + service (Phase 5 SP4)`.

---

## Task 7: Release detail — PIR tab

**Files:** Create `frontend/src/components/releases/ReleasePirTab.tsx`; Modify `frontend/src/pages/releases/ReleaseDetail.tsx`.

- [ ] **Step 1: Component** — `ReleasePirTab.tsx` (`{ releaseId }` prop): on mount `pirService.getForRelease(releaseId)`. If null → empty state ("No PIR for this release.") + **Create PIR** button (`pirService.create(releaseId, { status: 'draft' })` then reload). If present → an editable form: `summary`, `root_cause`, `what_went_well`, `what_went_wrong`, `action_plan` (multiline TextFields), a **Save** button (`pirService.update`), and a **status toggle** Draft⇄Complete (a Switch/Button that PATCHes `{status}`) showing a completion chip + `completed_at`. Use `useSnackbar` for errors. Mirror an existing release tab component (e.g. `ReleaseMainTab`/`ReleaseSystemsTab`) for structure.
- [ ] **Step 2: Wire tab** — in `ReleaseDetail.tsx`: add `import ReleasePirTab`, `<Tab label="PIR" />` after the Deployments tab (making it index 9), and `{activeTab === 9 && <ReleasePirTab releaseId={releaseId} />}` after the `activeTab === 8` panel. Update the header comment tab list.
- [ ] **Step 3:** `npx tsc --noEmit` → PASS; commit `feat(pir): release detail PIR tab (Phase 5 SP4)`.

---

## Task 8: Incident detail PIR panel + incident list PIR Status column

**Files:** Modify `frontend/src/pages/incidents/IncidentDetail.tsx`, `frontend/src/pages/incidents/IncidentList.tsx`.

- [ ] **Step 1: IncidentDetail PIR panel** — add a **PIR** panel/section: if `detail.pir` present, show its `status` (chip), `root_cause`, `action_plan`, `summary`, and a link to the PIR's release (`/releases/${detail.pir.release_id}` — render the release name if available, else "View release"). If `detail.pir` is null: show a **Create PIR** button that, when `detail.fix_release_id` is set, calls `pirService.create(detail.fix_release_id, { incident_id: detail.id })` then refetches the incident; when `detail.fix_release_id` is null, render the button **disabled** with a helper caption "Link a fix release to create a PIR." (There is no PIR panel in IncidentDetail yet — add it as a new section, following the existing section styling.)
- [ ] **Step 2: IncidentList PIR Status column** — add a column "PIR Status" rendering `pir_status` as a Chip: `complete` → success "Complete", `draft` → warning "Draft", `none` → "—".
- [ ] **Step 3:** `npx tsc --noEmit` → PASS; `npx vitest run src/store` sanity; commit `feat(pir): incident detail PIR panel + list PIR status (Phase 5 SP4)`.

---

## Task 9: Full verification

- [ ] **Step 1: Backend** — `uv run --directory /Users/peter/Developer/Code/projects/envmgr/backend pytest tests/ -q` → all pass (1 pre-existing skip ok).
- [ ] **Step 2: Frontend** — `npx tsc --noEmit` → clean; `npx vitest run --exclude 'e2e/**'` → pass.
- [ ] **Step 3: Manual eyeball (human)** — Open a release → **PIR** tab → Create PIR → fill fields → Save → toggle Complete (completion chip appears). On an incident with a linked fix release, open its detail → PIR panel → Create PIR → it appears; the incident list shows the "PIR Status" chip. On an incident with no fix release, the Create PIR button is disabled with the hint.

---

## Self-Review Notes

- **Spec coverage:** model+migration (T1); PIR + incident schemas (T2); service one-per-release/409/404/422/complete-clears/soft-delete-recreate/bulk-status (T3); API CRUD (T4); incident detail `pir` + list `pir_status` (T5); FE types/service (T6); release PIR tab (T7); incident panel + list column (T8); verification (T9). Non-goals (closure gate, custom fields, action-items, lifecycle SM) excluded. ✅
- **Type consistency:** `pir_service` method names (`get_for_release`/`get_for_incident`/`create_for_release`/`update`/`delete`/`pir_status_for_incidents`) are identical across service, API, and integration tasks. `PIRResponse`/`IncidentPirRef` fields match the TS `PIR`/incident `pir` shape. `_row(db, inc, tenant_id, pir_status="none")` signature updated consistently in the list endpoint and `_row` body. `pir_status` values `complete|draft|none` consistent backend↔frontend. Release PIR tab is index 9 (appended, no reindex).
- **Assumptions flagged in-task:** `rel_factory`/`incident_factory`/`demo_release_id`/`authed_client` fixture names (mirror sibling tests); the exact spot in `get_incident_detail`'s returned dict; PIR route non-collision with existing `/releases` routes (confirm via tests).
