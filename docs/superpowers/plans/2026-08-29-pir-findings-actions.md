# PIR Findings, Actions and Incident Citations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a PIR from five free-text blobs into a summary plus findings (went-well / went-wrong, each with root cause) carrying trackable actions (owner, due date, status), with incidents cited many-to-many against went-wrong findings — and remove the incident page's "link a fix release to create a PIR" dead end.

**Architecture:** Three new tables (`pir_finding`, `pir_action`, `pir_finding_incident`) hung off the existing one-per-release `pir` row, whose five text columns are backfilled into findings and actions and then dropped. One composite endpoint raises a citation from the incident side, creating the PIR if the chosen release has none. A tenant-wide `GET /pir-actions` worklist makes actions visible outside the release tab they were raised in. Nothing refuses anything.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); React 18 + TypeScript + MUI + Redux Toolkit (frontend). Tests: pytest (SQLite **and** PostgreSQL) + vitest/RTL.

**Spec:** [docs/superpowers/specs/2026-08-29-pir-findings-actions-design.md](../specs/2026-08-29-pir-findings-actions-design.md)

## Global Constraints

- **This work refuses nothing.** No release transition, no incident transition, no `can-deploy`, no readiness verdict changes. Task 9 is the named guard.
- Every tenant-scoped query filters `tenant_id`, taken from `current_user.active_tenant_id` (never `.tenant_id` — impersonation).
- All enum-ish columns are `String(n)`, never SQLAlchemy native enums.
- Soft delete via `deleted_at` on `pir_finding` and `pir_action`; **hard delete** on the junction `pir_finding_incident`.
- Services use `db.flush()`, never `db.commit()` — `get_db()` commits on success and the outbox depends on it.
- Migrations are hand-written DDL. Never `--autogenerate`. Never `alembic downgrade -1` against the dev database.
- Every write schema declares `model_config = ConfigDict(extra="forbid")`; `PATCH` handling keys on `model_fields_set`.
- New list endpoints take `pagination()` + `sorting()`, order by `apply_sort(...)` **then** a unique tiebreaker, and set `X-Total-Count`.
- A filter's "no selection" is an **omitted key**. Never the value `all` — that is `buildParams`' own sentinel and produces byte-identical params for two different states.
- Deadlines are days: compare due dates through `expiry_boundary` from `app/core/day_boundaries.py`. Do not write a second copy of that rule.
- Names travel **with the row**; never `#N` fallbacks. User-name lookups are **not** tenant-qualified (impersonation).
- Backend commands run from `backend/`: `uv run pytest -q`. PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`. Frontend from `frontend/`: `npm run test`, `npx tsc --noEmit`, `npm run lint`, `npm run build`.

## File Structure

**Backend — create**
- `backend/app/db/models/pir_finding.py` — `PirFinding`, `PirAction`, `PirFindingIncident`.
- `backend/app/db/migrations/versions/20260829_0900_pirfindings_pir_findings_actions.py` — the three tables.
- `backend/app/db/migrations/versions/20260829_0930_pirbackfill_retire_pir_free_text.py` — backfill, then drop five columns.
- `backend/app/services/pir_finding_service.py` — findings, actions, citations, the worklist query.
- `backend/app/api/v1/schemas/pir_finding.py` — finding/action/citation schemas.
- `backend/app/api/v1/pir_actions.py` — `GET /pir-actions`.
- `backend/tests/services/test_pir_finding_service.py`, `backend/tests/services/test_pir_action_service.py`, `backend/tests/services/test_pir_citation_service.py`
- `backend/tests/integration/test_pir_findings_api.py`, `backend/tests/integration/test_pir_actions_worklist.py`, `backend/tests/integration/test_incident_pir_citation_api.py`
- `backend/tests/test_pir_records_never_refuses.py`, `backend/tests/test_pir_backfill_migration.py`

**Backend — modify**
- `app/db/models/pir.py` (drop five columns) · `app/db/models/__init__.py` (register) · `app/api/v1/schemas/pir.py` · `app/api/v1/pir.py` · `app/services/pir_service.py` · `app/services/incident_service.py` · `app/api/v1/schemas/incident.py` · `app/api/v1/incidents.py` · `app/api/v1/releases.py` + `app/services/release_service.py` (`implemented` filter) · `app/main.py` (router) · `tests/test_sort_whitelist_contract.py` · existing `tests/services/test_pir_service.py` + `tests/integration/test_pir_api.py`.

**Frontend — create**
- `src/components/releases/pir/` — `PirFindingCard.tsx`, `PirFindingDialog.tsx`, `PirActionsTable.tsx`, `PirActionDialog.tsx`, `PirIncidentCitations.tsx`
- `src/components/incidents/LinkIncidentToPirDialog.tsx`
- `src/pages/pir/PirActionList.tsx`
- tests alongside each, under `__tests__/`.

**Frontend — modify**
- `src/types/pir.ts`, `src/types/incident.ts`, `src/services/pirService.ts`, `src/services/incidentService.ts`, `src/services/releaseService.ts`, `src/components/releases/ReleasePirTab.tsx`, `src/pages/incidents/IncidentDetail.tsx`, `src/pages/incidents/IncidentList.tsx`, `src/constants/sortWhitelists.json`, `src/App.tsx`, `src/components/navConfig.tsx`.

---
### Task 1: Models and the additive migration

**Files:**
- Create: `backend/app/db/models/pir_finding.py`
- Create: `backend/app/db/migrations/versions/20260829_0900_pirfindings_pir_findings_actions.py`
- Modify: `backend/app/db/models/__init__.py:64`
- Test: `backend/tests/test_pir_finding_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PirFinding` (`tenant_id, pir_id, kind, seq, title, detail, root_cause, created_by, deleted_at`), `PirAction` (`tenant_id, finding_id, seq, title, detail, owner_id, due_date, status, closed_at, closure_note, created_by, deleted_at`), `PirFindingIncident` (`tenant_id, finding_id, incident_id, note`), and the constants `FINDING_KINDS = {"went_well", "went_wrong"}`, `ACTION_STATUSES = {"open", "in_progress", "done", "cancelled"}`, `CLOSED_ACTION_STATUSES = {"done", "cancelled"}`. Alembic revision id `pirfindings`, down-revision `rollbackgov`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_pir_finding_models.py`:

```python
"""The three tables PIR findings hang off, and the invariants their columns carry."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.pir import PIR
from app.db.models.pir_finding import (
    ACTION_STATUSES,
    CLOSED_ACTION_STATUSES,
    FINDING_KINDS,
    PirAction,
    PirFinding,
    PirFindingIncident,
)
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.db.models.incident import Incident

UTC = timezone.utc


async def _release(db, tenant_id: int, user_id: int) -> Release:
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name="RT-models", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl)
    await db.flush()
    r = Release(tenant_id=tenant_id, name="R-models", release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(r)
    await db.flush()
    return r


async def _pir(db, tenant_id: int, user_id: int) -> PIR:
    r = await _release(db, tenant_id, user_id)
    p = PIR(tenant_id=tenant_id, release_id=r.id, summary="s", status="draft", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_vocabularies_are_what_the_spec_says():
    assert FINDING_KINDS == {"went_well", "went_wrong"}
    assert ACTION_STATUSES == {"open", "in_progress", "done", "cancelled"}
    assert CLOSED_ACTION_STATUSES == {"done", "cancelled"}


@pytest.mark.asyncio
async def test_a_finding_persists_with_its_root_cause(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1,
                   title="No load test before go-live", detail="d",
                   root_cause="Perf gate is optional", created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    got = (await db_session.execute(select(PirFinding).where(PirFinding.id == f.id))).scalar_one()
    assert (got.kind, got.seq, got.root_cause) == ("went_wrong", 1, "Perf gate is optional")
    assert got.deleted_at is None
    assert got.created_at is not None and got.updated_at is not None


@pytest.mark.asyncio
async def test_a_went_well_finding_may_carry_a_root_cause_and_an_action(db_session, tenant, user):
    """Nothing REFUSES a root cause on a went-well finding, and an action may hang off one:
    'codify this in the release template' is a real PIR outcome."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_well", seq=1,
                   title="Canary caught it", root_cause="Canary ran for 30 minutes",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    a = PirAction(tenant_id=tenant.id, finding_id=f.id, seq=1, title="Codify canary in the template",
                  status="open", created_by=user.id)
    db_session.add(a)
    await db_session.flush()
    assert a.id is not None


@pytest.mark.asyncio
async def test_an_action_defaults_to_open_and_holds_owner_and_due_date(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1, title="t",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    due = datetime(2026, 9, 30, tzinfo=UTC)
    a = PirAction(tenant_id=tenant.id, finding_id=f.id, seq=1, title="Add a perf gate",
                  owner_id=user.id, due_date=due, created_by=user.id)
    db_session.add(a)
    await db_session.flush()
    got = (await db_session.execute(select(PirAction).where(PirAction.id == a.id))).scalar_one()
    assert got.status == "open"
    assert got.owner_id == user.id
    assert got.closed_at is None and got.closure_note is None


@pytest.mark.asyncio
async def test_one_incident_cites_one_finding_only_once(db_session, tenant, user):
    """uq_pir_finding_incident. The citation is a fact, not a counter."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=1, title="t",
                   created_by=user.id)
    db_session.add(f)
    await db_session.flush()
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db_session.add(inc)
    await db_session.flush()

    db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id, incident_id=inc.id,
                                      note="first"))
    await db_session.flush()
    db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id, incident_id=inc.id,
                                      note="again"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_one_incident_may_cite_two_findings(db_session, tenant, user):
    """One incident often exposes two distinct process failures — neither direction is 1:1."""
    pir = await _pir(db_session, tenant.id, user.id)
    findings = []
    for seq in (1, 2):
        f = PirFinding(tenant_id=tenant.id, pir_id=pir.id, kind="went_wrong", seq=seq,
                       title=f"failure {seq}", created_by=user.id)
        db_session.add(f)
        findings.append(f)
    await db_session.flush()
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db_session.add(inc)
    await db_session.flush()
    for f in findings:
        db_session.add(PirFindingIncident(tenant_id=tenant.id, finding_id=f.id,
                                          incident_id=inc.id))
    await db_session.flush()
    rows = (await db_session.execute(
        select(PirFindingIncident).where(PirFindingIncident.incident_id == inc.id))).scalars().all()
    assert len(rows) == 2
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/test_pir_finding_models.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.pir_finding'`.

- [ ] **Step 3: Write the models**

Create `backend/app/db/models/pir_finding.py`:

```python
"""What a post-implementation review actually found, and what is being done about it.

A PIR is one row per release (`pir`) holding a summary. Everything the review
FOUND lives here: a `PirFinding` is one thing that went well or one thing that
went wrong, and a `PirAction` is a process fix hanging off a finding.

Two rules worth keeping straight:

- Actions hang off a FINDING, not off the PIR, so "which failure is this fix
  for" is structural rather than prose. They are allowed on a `went_well`
  finding too — "codify this in the release template" is a real PIR outcome.
- There is deliberately no denormalised `release_id`/`pir_id` on `PirAction`.
  The cross-release worklist joins action -> finding -> pir -> release. A
  denormalised copy is one more thing that can disagree with the row it was
  copied from.

`PirFindingIncident` is the citation: an incident, raised by the ITIL process or
by monitoring, offered as EVIDENCE that a process failed. The PIR fixes the
process that let the incident reach production; it does not fix the incident.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

FINDING_KINDS = {"went_well", "went_wrong"}
ACTION_STATUSES = {"open", "in_progress", "done", "cancelled"}
# The two statuses that stamp `closed_at`. Leaving either one clears it again —
# a reopened action has no closing date, and a stale one would be read as a
# closure that happened.
CLOSED_ACTION_STATUSES = {"done", "cancelled"}
# The statuses an overdue due date can still be overdue ON. A done or cancelled
# action is not overdue however far past its date it sits.
LIVE_ACTION_STATUSES = {"open", "in_progress"}


class PirFinding(Base):
    __tablename__ = "pir_finding"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    pir_id: Mapped[int] = mapped_column(
        ForeignKey("pir.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # went_well | went_wrong
    seq: Mapped[int] = mapped_column(Integer, nullable=False)      # per (pir_id, kind)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Meaningful on a went_wrong finding. Nothing refuses one on a went_well
    # finding: a half-useful note on a thing that worked is not worth a 422.
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_finding_tenant_pir", "tenant_id", "pir_id"),
    )


class PirAction(Base):
    __tablename__ = "pir_action"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # per finding_id
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closure_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_pir_action_tenant_finding", "tenant_id", "finding_id"),
        Index("ix_pir_action_tenant_status", "tenant_id", "status"),
    )


class PirFindingIncident(Base):
    """An incident offered as evidence for a finding. Hard-deleted: removing a
    citation is a correction, not history — the junction-record convention in
    CLAUDE.md."""

    __tablename__ = "pir_finding_incident"

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incident.id"), nullable=False, index=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("finding_id", "incident_id", name="uq_pir_finding_incident"),
        Index("ix_pir_finding_incident_tenant_incident", "tenant_id", "incident_id"),
    )
```

- [ ] **Step 4: Register the models on `Base.metadata`**

In `backend/app/db/models/__init__.py`, immediately after the existing line 64 (`from app.db.models.pir import PIR  # noqa: F401`), add:

```python
from app.db.models.pir_finding import (  # noqa: F401
    PirAction,
    PirFinding,
    PirFindingIncident,
)
```

- [ ] **Step 5: Run the model tests and watch them pass**

Run: `cd backend && uv run pytest tests/test_pir_finding_models.py -q`
Expected: 6 passed.

- [ ] **Step 6: Write the migration**

Confirm the head first: `cd backend && uv run alembic heads` — expect `rollbackgov`. Then create `backend/app/db/migrations/versions/20260829_0900_pirfindings_pir_findings_actions.py`:

```python
"""PIR findings, actions and incident citations — the three new tables.

Revision ID: pirfindings
Revises: rollbackgov
Create Date: 2026-08-29 09:00:00.000000

Additive only: three new tables, no change to any existing table and no
backfill. The follow-on revision `pirbackfill` moves the existing free text on
`pir` into these tables and then drops those columns; splitting the two keeps
the destructive half in its own revision, which can be reviewed and rehearsed
on a scratch database on its own.

See app/db/models/pir_finding.py for what each table records and why.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'pirfindings'
down_revision: Union[str, None] = 'rollbackgov'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pir_finding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("pir_id", sa.Integer(), sa.ForeignKey("pir.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # `Base` declares `id` with index=True, so create_all builds this index on
    # every model-defined table. Without it here a migration-built database
    # differs from a create_all-built one, and test_migration_schema_drift.py
    # (column NAME sets only) would not catch the difference.
    op.create_index("ix_pir_finding_id", "pir_finding", ["id"])
    op.create_index("ix_pir_finding_tenant_id", "pir_finding", ["tenant_id"])
    op.create_index("ix_pir_finding_pir_id", "pir_finding", ["pir_id"])
    op.create_index("ix_pir_finding_tenant_pir", "pir_finding", ["tenant_id", "pir_id"])

    op.create_table(
        "pir_action",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("finding_id", sa.Integer(),
                  sa.ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closure_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_pir_action_id", "pir_action", ["id"])
    op.create_index("ix_pir_action_tenant_id", "pir_action", ["tenant_id"])
    op.create_index("ix_pir_action_finding_id", "pir_action", ["finding_id"])
    op.create_index("ix_pir_action_tenant_finding", "pir_action", ["tenant_id", "finding_id"])
    op.create_index("ix_pir_action_tenant_status", "pir_action", ["tenant_id", "status"])

    op.create_table(
        "pir_finding_incident",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("finding_id", sa.Integer(),
                  sa.ForeignKey("pir_finding.id", ondelete="CASCADE"), nullable=False),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incident.id"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("finding_id", "incident_id", name="uq_pir_finding_incident"),
    )
    op.create_index("ix_pir_finding_incident_id", "pir_finding_incident", ["id"])
    op.create_index("ix_pir_finding_incident_tenant_id", "pir_finding_incident", ["tenant_id"])
    op.create_index("ix_pir_finding_incident_finding_id", "pir_finding_incident", ["finding_id"])
    op.create_index("ix_pir_finding_incident_incident_id", "pir_finding_incident", ["incident_id"])
    op.create_index("ix_pir_finding_incident_tenant_incident", "pir_finding_incident",
                    ["tenant_id", "incident_id"])


def downgrade() -> None:
    op.drop_table("pir_finding_incident")
    op.drop_table("pir_action")
    op.drop_table("pir_finding")
```

- [ ] **Step 7: Run the migration against a scratch database, not the dev one**

Run:
```bash
cd backend
uv run pytest tests/test_migration_schema_drift.py -q
```
Expected: PASS (or `skipped` if no PostgreSQL is reachable — then start it with `docker-compose up -d` and re-run; a skip here proves nothing).

`alembic downgrade -1` steps back from the CURRENT head, not from your revision. Never run it against the dev database — doing that once dropped `tenant_secret` and wiped a stored GitHub token.

- [ ] **Step 8: Apply to the dev database**

Run: `cd backend && uv run alembic upgrade head && uv run alembic current`
Expected: `pirfindings (head)`.

- [ ] **Step 9: Run the full backend suite on both engines**

Run:
```bash
cd backend && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
```
Expected: PASS on both. Nothing existing changed, so a failure here is a real regression, not a rebase artifact.

- [ ] **Step 10: Commit**

```bash
git add backend/app/db/models/pir_finding.py backend/app/db/models/__init__.py \
        backend/app/db/migrations/versions/20260829_0900_pirfindings_pir_findings_actions.py \
        backend/tests/test_pir_finding_models.py
git commit -m "feat(pir): findings, actions and incident-citation tables"
```

---
### Task 2: Finding service, schemas and routes

**Files:**
- Create: `backend/app/services/pir_finding_service.py`
- Create: `backend/app/api/v1/schemas/pir_finding.py`
- Modify: `backend/app/api/v1/pir.py`, `backend/app/api/v1/schemas/pir.py`
- Test: `backend/tests/services/test_pir_finding_service.py`, `backend/tests/integration/test_pir_findings_api.py`

**Interfaces:**
- Consumes: `PirFinding`, `FINDING_KINDS` from Task 1.
- Produces:
  - `pir_finding_service.get_pir_or_404(db, tenant_id, release_id) -> PIR`
  - `pir_finding_service.get_finding(db, tenant_id, finding_id) -> PirFinding` (404s)
  - `pir_finding_service.create_finding(db, tenant_id, pir, data, user_id) -> PirFinding`
  - `pir_finding_service.update_finding(db, tenant_id, finding_id, data) -> PirFinding`
  - `pir_finding_service.delete_finding(db, tenant_id, finding_id) -> None`
  - `pir_finding_service.findings_for_pir(db, tenant_id, pir_id) -> list[PirFinding]`
  - Schemas `PirFindingCreate`, `PirFindingUpdate`, `PirFindingResponse` (fields: `id, kind, seq, title, detail, root_cause`; `actions` and `incidents` are added in Tasks 3 and 4).
  - `PIRResponse.findings: list[PirFindingResponse]`.

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/services/test_pir_finding_service.py`. Reuse the `_release`/`_pir` helpers from `tests/test_pir_finding_models.py` by copying them in — this file uses the `tenant`/`user` fixtures throughout and never mixes them with `auth_headers` (which authenticates into `test_tenant`, a **different** tenant; mixing the two passes vacuously).

```python
"""pir_finding_service — the rules a finding carries."""
import pytest
from datetime import timezone
from fastapi import HTTPException

from app.api.v1.schemas.pir_finding import PirFindingCreate, PirFindingUpdate
from app.db.models.pir import PIR
from app.db.models.pir_finding import PirFinding
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import pir_finding_service

UTC = timezone.utc


async def _pir(db, tenant_id, user_id, name="R"):
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"RT-{name}", is_default=False,
        definition={"states": [{"key": "draft", "label": "Draft", "is_initial": True,
                                "is_terminal": False}], "transitions": [], "field_permissions": {}},
    )
    db.add(tpl)
    await db.flush()
    r = Release(tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
                lifecycle_template_id=tpl.id, status="draft", raised_by=user_id)
    db.add(r)
    await db.flush()
    p = PIR(tenant_id=tenant_id, release_id=r.id, summary=None, status="draft", created_by=user_id)
    db.add(p)
    await db.flush()
    return p


@pytest.mark.asyncio
async def test_seq_is_per_pir_and_per_kind(db_session, tenant, user):
    """Two lists on one page, each numbered from 1 — a went-wrong finding does not
    take a number away from the went-well list above it."""
    pir = await _pir(db_session, tenant.id, user.id)
    a = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="A"), user.id)
    b = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="B"), user.id)
    c = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_well", title="C"), user.id)
    assert (a.seq, b.seq, c.seq) == (1, 2, 1)


@pytest.mark.asyncio
async def test_a_deleted_finding_does_not_hold_its_number(db_session, tenant, user):
    """seq is the max of the LIVE rows plus one. Deleting #2 of three and adding
    another must not collide with the surviving #3."""
    pir = await _pir(db_session, tenant.id, user.id)
    ids = []
    for t in ("A", "B", "C"):
        f = await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title=t), user.id)
        ids.append(f.id)
    await pir_finding_service.delete_finding(db_session, tenant.id, ids[1])
    d = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="D"), user.id)
    assert d.seq == 4


@pytest.mark.asyncio
async def test_update_leaves_omitted_keys_alone_and_an_explicit_null_clears(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir,
        PirFindingCreate(kind="went_wrong", title="T", detail="D", root_cause="RC"), user.id)

    await pir_finding_service.update_finding(
        db_session, tenant.id, f.id, PirFindingUpdate(title="T2"))
    assert (f.title, f.detail, f.root_cause) == ("T2", "D", "RC")

    await pir_finding_service.update_finding(
        db_session, tenant.id, f.id, PirFindingUpdate(root_cause=None))
    assert f.root_cause is None
    assert f.detail == "D"


@pytest.mark.asyncio
async def test_kind_is_immutable_once_set(db_session, tenant, user):
    """A finding's kind is which LIST it is in. Flipping it would move an item
    between 'keep doing this' and 'this failed' while its root cause and actions
    followed it across — delete and re-raise instead."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.update_finding(
            db_session, tenant.id, f.id, PirFindingUpdate(kind="went_well"))
    assert exc.value.status_code == 422
    assert "kind" in exc.value.detail


@pytest.mark.asyncio
async def test_a_deleted_finding_is_gone_from_reads_and_from_get(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    await pir_finding_service.delete_finding(db_session, tenant.id, f.id)
    assert await pir_finding_service.findings_for_pir(db_session, tenant.id, pir.id) == []
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.get_finding(db_session, tenant.id, f.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_findings_read_back_went_well_first_then_by_seq(db_session, tenant, user):
    """The read order IS the page order, decided once on the server, so two
    surfaces cannot render the same review in two orders."""
    pir = await _pir(db_session, tenant.id, user.id)
    for kind, title in (("went_wrong", "W1"), ("went_well", "G1"), ("went_wrong", "W2"),
                        ("went_well", "G2")):
        await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind=kind, title=title), user.id)
    rows = await pir_finding_service.findings_for_pir(db_session, tenant.id, pir.id)
    assert [r.title for r in rows] == ["G1", "G2", "W1", "W2"]


@pytest.mark.asyncio
async def test_a_finding_in_another_tenant_is_a_404_not_someone_elses_row(db_session, tenant,
                                                                          other_tenant, user,
                                                                          other_user):
    """Mutation check: drop the tenant_id filter in get_finding and this test must
    fail. The missing tenant filter appeared eight times on A1 and no pre-existing
    test caught one of them."""
    theirs = await _pir(db_session, other_tenant.id, other_user.id, name="Theirs")
    f = await pir_finding_service.create_finding(
        db_session, other_tenant.id, theirs, PirFindingCreate(kind="went_wrong", title="T"),
        other_user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.get_finding(db_session, tenant.id, f.id)
    assert exc.value.status_code == 404
```

If `other_tenant`/`other_user` fixtures do not exist in `backend/tests/conftest.py`, create the second tenant and user inline in that last test with `Tenant(name="Other Org", slug="other-org")` and `factories.ensure_user(db_session, other_tenant.id, username="other")` — check `conftest.py` first, do not assume.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/services/test_pir_finding_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.v1.schemas.pir_finding'`.

- [ ] **Step 3: Write the schemas**

Create `backend/app/api/v1/schemas/pir_finding.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.pir_finding import FINDING_KINDS


class PirFindingCreate(BaseModel):
    kind: str
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    root_cause: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in FINDING_KINDS:
            raise ValueError(f"kind must be one of {sorted(FINDING_KINDS)}")
        return v


class PirFindingUpdate(BaseModel):
    # `kind` is accepted so an attempt to change it earns an explicit 422 naming
    # the field, rather than `extra="forbid"`'s generic "extra inputs are not
    # permitted" — the reader needs to know it is immutable, not misspelled.
    kind: Optional[str] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    detail: Optional[str] = None
    root_cause: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class PirFindingResponse(BaseModel):
    id: int
    kind: str
    seq: int
    title: str
    detail: Optional[str]
    root_cause: Optional[str]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/pir_finding_service.py`:

```python
"""Findings on a post-implementation review.

A finding is one thing the review found: `went_well` (keep doing it) or
`went_wrong` (analyse it, then act). `kind` is immutable once set — it is which
LIST the item is in, and flipping it would drag a root cause and its actions
across from "this failed" to "keep doing this".

Everything here is tenant-scoped on the way in. `get_finding` filters
`tenant_id` and that filter is load-bearing, not defence in depth: without it a
caller with any finding id reads another tenant's review.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pir import PIR
from app.db.models.pir_finding import PirFinding

# went_well first, so the page reads "here is what worked" before "here is what
# did not". Decided once here rather than per surface.
_KIND_ORDER = {"went_well": 0, "went_wrong": 1}


async def get_pir_or_404(db: AsyncSession, tenant_id: int, release_id: int) -> PIR:
    pir = (await db.execute(select(PIR).where(
        PIR.release_id == release_id, PIR.tenant_id == tenant_id, PIR.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if pir is None:
        raise HTTPException(status_code=404, detail="PIR not found")
    return pir


async def get_finding(db: AsyncSession, tenant_id: int, finding_id: int) -> PirFinding:
    f = (await db.execute(select(PirFinding).where(
        PirFinding.id == finding_id,
        PirFinding.tenant_id == tenant_id,
        PirFinding.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if f is None:
        raise HTTPException(status_code=404, detail="Finding not found")
    return f


async def _next_seq(db: AsyncSession, pir_id: int, kind: str) -> int:
    """Max of the LIVE rows plus one, per (pir, kind).

    Counting rows instead would reuse a deleted item's number and collide with a
    survivor that already holds it.
    """
    current = (await db.execute(select(func.max(PirFinding.seq)).where(
        PirFinding.pir_id == pir_id,
        PirFinding.kind == kind,
        PirFinding.deleted_at.is_(None),
    ))).scalar_one_or_none()
    return (current or 0) + 1


async def create_finding(
    db: AsyncSession, tenant_id: int, pir: PIR, data, user_id: Optional[int]
) -> PirFinding:
    finding = PirFinding(
        tenant_id=tenant_id,
        pir_id=pir.id,
        kind=data.kind,
        seq=await _next_seq(db, pir.id, data.kind),
        title=data.title,
        detail=data.detail,
        root_cause=data.root_cause,
        created_by=user_id,
    )
    db.add(finding)
    await db.flush()
    return finding


async def update_finding(db: AsyncSession, tenant_id: int, finding_id: int, data) -> PirFinding:
    finding = await get_finding(db, tenant_id, finding_id)
    payload = data.model_dump(exclude_unset=True)
    if "kind" in payload and payload["kind"] != finding.kind:
        raise HTTPException(
            status_code=422,
            detail="kind cannot be changed; delete the finding and raise it under the other kind",
        )
    payload.pop("kind", None)
    if "title" in payload and payload["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")
    for key, value in payload.items():
        setattr(finding, key, value)
    await db.flush()
    return finding


async def delete_finding(db: AsyncSession, tenant_id: int, finding_id: int) -> None:
    finding = await get_finding(db, tenant_id, finding_id)
    finding.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def findings_for_pir(db: AsyncSession, tenant_id: int, pir_id: int) -> list[PirFinding]:
    rows = list((await db.execute(select(PirFinding).where(
        PirFinding.pir_id == pir_id,
        PirFinding.tenant_id == tenant_id,
        PirFinding.deleted_at.is_(None),
    ))).scalars().all())
    # Ordered in Python, not SQL: the kind order is a two-value preference, not a
    # collation, and a CASE in the query would need reproducing anywhere else
    # that reads these rows. A PIR holds tens of findings, not thousands.
    return sorted(rows, key=lambda f: (_KIND_ORDER[f.kind], f.seq))
```

- [ ] **Step 5: Run the service tests and watch them pass**

Run: `cd backend && uv run pytest tests/services/test_pir_finding_service.py -q`
Expected: 7 passed.

- [ ] **Step 6: Prove the tenant filter is load-bearing**

Comment out the `PirFinding.tenant_id == tenant_id` line in `get_finding`, run the file again, and confirm `test_a_finding_in_another_tenant_is_a_404_not_someone_elses_row` FAILS. Restore the line and confirm it passes. A guard nobody has watched fail is a guard nobody knows works.

- [ ] **Step 7: Write the failing API tests**

Create `backend/tests/integration/test_pir_findings_api.py`, copying the `authed_client` and `demo_release_id` fixtures verbatim from `tests/integration/test_pir_api.py` (same `tenant`/`user` fixtures, same `seed_incident_defaults_for_tenant` call).

```python
@pytest.mark.asyncio
async def test_findings_come_back_on_the_pir(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    created = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test", "root_cause": "Perf gate optional"},
    )
    assert created.status_code == 201, created.text

    got = await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")
    body = got.json()
    assert [f["title"] for f in body["findings"]] == ["No load test"]
    assert body["findings"][0]["root_cause"] == "Perf gate optional"
    assert body["findings"][0]["seq"] == 1


@pytest.mark.asyncio
async def test_a_finding_on_a_release_with_no_pir_is_a_404(authed_client, demo_release_id):
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_an_unknown_kind_is_a_422(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_sideways", "title": "T"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_dropped(authed_client, demo_release_id):
    """extra='forbid'. FastAPI and Pydantic drop unknown keys silently, and this
    codebase has shipped that bug three times."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T", "rootcause": "typo"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_patch_and_delete_a_finding(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_well", "title": "Canary caught it"},
    )).json()["id"]

    patched = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}", json={"detail": "ran 30 min"})
    assert patched.status_code == 200
    assert patched.json()["title"] == "Canary caught it"
    assert patched.json()["detail"] == "ran 30 min"

    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}")).status_code == 204
    assert (await authed_client.get(
        f"/api/v1/releases/{demo_release_id}/pir")).json()["findings"] == []
```

- [ ] **Step 8: Run them and watch them fail**

Run: `cd backend && uv run pytest tests/integration/test_pir_findings_api.py -q`
Expected: FAIL — 404s from routes that do not exist yet.

- [ ] **Step 9: Add `findings` to the PIR read model**

In `backend/app/api/v1/schemas/pir.py`, import the finding schema and add the field to `PIRResponse`:

```python
from app.api.v1.schemas.pir_finding import PirFindingResponse
```
```python
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
    findings: list[PirFindingResponse] = []
    model_config = ConfigDict(from_attributes=True)
```

The legacy text fields stay for now; Task 6 removes them. `findings` defaults to `[]` so nothing that constructs a `PIRResponse` today breaks — but note that a default is what let a response field render `null` at four of five construction sites on A1 with the suite green, so Step 7's read-back assertion is what actually guards this, not the type.

- [ ] **Step 10: Add the routes**

In `backend/app/api/v1/pir.py`, import the service and schemas, and change `get_pir` to hydrate findings:

```python
from app.services import pir_finding_service
from app.api.v1.schemas.pir_finding import (
    PirFindingCreate,
    PirFindingResponse,
    PirFindingUpdate,
)


async def _hydrate(db: AsyncSession, tenant_id: int, pir):
    """One PIR with its findings, built once so every route returns the same shape."""
    if pir is None:
        return None
    body = PIRResponse.model_validate(pir).model_dump()
    body["findings"] = [
        PirFindingResponse.model_validate(f).model_dump()
        for f in await pir_finding_service.findings_for_pir(db, tenant_id, pir.id)
    ]
    return body


@router.get("/{release_id}/pir", response_model=PIRResponse | None)
async def get_pir(
    release_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    return await _hydrate(db, tenant_id, await pir_service.get_for_release(db, tenant_id, release_id))


@router.post("/{release_id}/pir/findings", response_model=PirFindingResponse,
             status_code=status.HTTP_201_CREATED)
async def create_finding(
    release_id: int,
    data: PirFindingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    pir = await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await pir_finding_service.create_finding(db, tenant_id, pir, data, current_user.id)


@router.patch("/{release_id}/pir/findings/{finding_id}", response_model=PirFindingResponse)
async def update_finding(
    release_id: int,
    finding_id: int,
    data: PirFindingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await pir_finding_service.update_finding(db, tenant_id, finding_id, data)


@router.delete("/{release_id}/pir/findings/{finding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_finding(
    release_id: int,
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.delete_finding(db, tenant_id, finding_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

`create_pir` and `update_pir` keep returning the bare model for now; Task 6 routes them through `_hydrate` as well.

- [ ] **Step 11: Run the API tests and watch them pass**

Run: `cd backend && uv run pytest tests/integration/test_pir_findings_api.py -q`
Expected: 5 passed.

- [ ] **Step 12: Run the whole PIR + incident surface on both engines**

Run:
```bash
cd backend && uv run pytest tests/services/test_pir_service.py tests/integration/test_pir_api.py \
  tests/services/test_pir_finding_service.py tests/integration/test_pir_findings_api.py \
  tests/integration/test_incidents_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_pir_finding_service.py tests/integration/test_pir_findings_api.py -q
```
Expected: PASS on both.

- [ ] **Step 13: Commit**

```bash
git add backend/app/services/pir_finding_service.py backend/app/api/v1/schemas/pir_finding.py \
        backend/app/api/v1/schemas/pir.py backend/app/api/v1/pir.py \
        backend/tests/services/test_pir_finding_service.py \
        backend/tests/integration/test_pir_findings_api.py
git commit -m "feat(pir): findings on a PIR, with an immutable kind and per-kind numbering"
```

---
### Task 3: Actions on a finding

**Files:**
- Modify: `backend/app/services/pir_finding_service.py`, `backend/app/api/v1/schemas/pir_finding.py`, `backend/app/api/v1/pir.py`
- Test: `backend/tests/services/test_pir_action_service.py`, add to `backend/tests/integration/test_pir_findings_api.py`

**Interfaces:**
- Consumes: `get_finding`, `findings_for_pir` (Task 2); `PirAction`, `ACTION_STATUSES`, `CLOSED_ACTION_STATUSES` (Task 1).
- Produces:
  - `pir_finding_service.create_action(db, tenant_id, finding, data, user_id) -> PirAction`
  - `pir_finding_service.update_action(db, tenant_id, action_id, data) -> PirAction`
  - `pir_finding_service.delete_action(db, tenant_id, action_id) -> None`
  - `pir_finding_service.actions_for_findings(db, tenant_id, finding_ids) -> dict[int, list[PirAction]]` — batched, one query for the whole PIR.
  - Schemas `PirActionCreate`, `PirActionUpdate`, `PirActionResponse` (`id, seq, title, detail, owner_id, owner_username, due_date, status, closed_at, closure_note, is_overdue`).
  - `PirFindingResponse.actions: list[PirActionResponse]`.

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/services/test_pir_action_service.py` (copy the `_pir` helper from `tests/services/test_pir_finding_service.py`):

```python
"""pir_finding_service — actions: closure stamping, and what 'overdue' means."""
import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException

from app.api.v1.schemas.pir_finding import PirActionCreate, PirActionUpdate, PirFindingCreate
from app.services import pir_finding_service

UTC = timezone.utc


@pytest.fixture
async def finding(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    return await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)


@pytest.mark.asyncio
async def test_an_action_starts_open_with_no_closing_date(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="Add a perf gate"), user.id)
    assert (a.status, a.closed_at, a.seq) == ("open", None, 1)


@pytest.mark.asyncio
async def test_closing_stamps_closed_at_and_reopening_clears_it(db_session, tenant, user, finding):
    """A reopened action has no closing date. A stale one reads as a closure that
    happened, which is exactly the claim the worklist exists to disprove."""
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="done", closure_note="shipped"))
    assert a.closed_at is not None
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="in_progress"))
    assert a.closed_at is None


@pytest.mark.asyncio
async def test_cancelled_closes_too(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="cancelled"))
    assert a.closed_at is not None


@pytest.mark.asyncio
async def test_an_unknown_status_is_a_422(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    with pytest.raises(ValueError):
        PirActionUpdate(status="nearly")


@pytest.mark.asyncio
async def test_an_action_is_overdue_only_after_its_whole_due_day(db_session, tenant, user, finding):
    """A DEADLINE IS A DAY. The UI writes a due date at T00:00:00Z; at instant
    precision an action due today reads overdue from one minute past midnight."""
    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    today = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="due today", due_date=datetime(2026, 9, 10, tzinfo=UTC)), user.id)
    yesterday = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="due yesterday", due_date=datetime(2026, 9, 9, tzinfo=UTC)), user.id)
    assert pir_finding_service.is_overdue(today, now) is False
    assert pir_finding_service.is_overdue(yesterday, now) is True


@pytest.mark.asyncio
async def test_a_closed_action_is_never_overdue(db_session, tenant, user, finding):
    now = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding,
        PirActionCreate(title="T", due_date=datetime(2026, 1, 1, tzinfo=UTC)), user.id)
    assert pir_finding_service.is_overdue(a, now) is True
    await pir_finding_service.update_action(
        db_session, tenant.id, a.id, PirActionUpdate(status="done"))
    assert pir_finding_service.is_overdue(a, now) is False


@pytest.mark.asyncio
async def test_an_action_with_no_due_date_is_never_overdue(db_session, tenant, user, finding):
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="T"), user.id)
    assert pir_finding_service.is_overdue(a, datetime(2030, 1, 1, tzinfo=UTC)) is False


@pytest.mark.asyncio
async def test_actions_are_batched_one_query_for_the_whole_pir(db_session, tenant, user, finding):
    """A 40-finding PIR must not be 40 queries. `actions_for_findings` keys by
    finding id and returns [] for a finding with none, so no caller has to guess."""
    a = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="A"), user.id)
    b = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="B"), user.id)
    by_finding = await pir_finding_service.actions_for_findings(
        db_session, tenant.id, [finding.id, finding.id + 999])
    assert [x.title for x in by_finding[finding.id]] == ["A", "B"]
    assert by_finding[finding.id + 999] == []


@pytest.mark.asyncio
async def test_a_deleted_action_is_gone_and_does_not_hold_its_number(db_session, tenant, user,
                                                                     finding):
    first = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="A"), user.id)
    second = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="B"), user.id)
    await pir_finding_service.delete_action(db_session, tenant.id, first.id)
    third = await pir_finding_service.create_action(
        db_session, tenant.id, finding, PirActionCreate(title="C"), user.id)
    assert third.seq == 3
    by_finding = await pir_finding_service.actions_for_findings(db_session, tenant.id, [finding.id])
    assert [x.title for x in by_finding[finding.id]] == ["B", "C"]


@pytest.mark.asyncio
async def test_an_action_in_another_tenant_is_a_404(db_session, tenant, other_tenant, user,
                                                    other_user):
    theirs_pir = await _pir(db_session, other_tenant.id, other_user.id, name="Theirs")
    theirs_finding = await pir_finding_service.create_finding(
        db_session, other_tenant.id, theirs_pir, PirFindingCreate(kind="went_wrong", title="T"),
        other_user.id)
    theirs = await pir_finding_service.create_action(
        db_session, other_tenant.id, theirs_finding, PirActionCreate(title="T"), other_user.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.update_action(
            db_session, tenant.id, theirs.id, PirActionUpdate(status="done"))
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/services/test_pir_action_service.py -q`
Expected: FAIL — `ImportError: cannot import name 'PirActionCreate'`.

- [ ] **Step 3: Add the action schemas**

Append to `backend/app/api/v1/schemas/pir_finding.py`:

```python
from app.db.models.pir_finding import ACTION_STATUSES


class PirActionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: str = "open"
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(ACTION_STATUSES)}")
        return v


class PirActionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    detail: Optional[str] = None
    owner_id: Optional[int] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = None
    closure_note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @field_validator("status")
    @classmethod
    def _status(cls, v):
        if v is not None and v not in ACTION_STATUSES:
            raise ValueError(f"status must be one of {sorted(ACTION_STATUSES)}")
        return v


class PirActionResponse(BaseModel):
    id: int
    finding_id: int
    seq: int
    title: str
    detail: Optional[str]
    owner_id: Optional[int]
    # Resolved server-side and travelling WITH the row. Never `#N`, and never
    # looked up client-side against a capped collection.
    owner_username: Optional[str]
    due_date: Optional[datetime]
    status: str
    closed_at: Optional[datetime]
    closure_note: Optional[str]
    is_overdue: bool
    model_config = ConfigDict(from_attributes=True)
```

Then add `actions: list[PirActionResponse] = []` to `PirFindingResponse`.

- [ ] **Step 4: Add the action service functions**

Append to `backend/app/services/pir_finding_service.py`:

```python
from app.core.day_boundaries import expiry_boundary
from app.db.models.pir_finding import (
    CLOSED_ACTION_STATUSES,
    LIVE_ACTION_STATUSES,
    PirAction,
)
from app.db.models.user import User


def is_overdue(action: PirAction, now: datetime) -> bool:
    """Past its due DAY, and still live.

    `expiry_boundary` is the one place that decides a deadline is a day — the
    same rule A4's escalations, B2's grace periods, B5's teardown dates and C2's
    waivers follow. Do not write a second copy of it.

    `_utc` normalisation matters: SQLite hands back naive datetimes where
    PostgreSQL hands back aware ones, and comparing the two is a TypeError — an
    engine-dependent 500 invisible on one leg of CI.
    """
    if action.due_date is None or action.status not in LIVE_ACTION_STATUSES:
        return False
    due = action.due_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due < expiry_boundary(now)


async def get_action(db: AsyncSession, tenant_id: int, action_id: int) -> PirAction:
    a = (await db.execute(select(PirAction).where(
        PirAction.id == action_id,
        PirAction.tenant_id == tenant_id,
        PirAction.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if a is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return a


async def _next_action_seq(db: AsyncSession, finding_id: int) -> int:
    current = (await db.execute(select(func.max(PirAction.seq)).where(
        PirAction.finding_id == finding_id, PirAction.deleted_at.is_(None),
    ))).scalar_one_or_none()
    return (current or 0) + 1


async def _validate_owner(db: AsyncSession, tenant_id: int, owner_id: Optional[int]) -> None:
    """An owner must be a live user in this tenant.

    Deliberately does NOT check `is_active`: an action assigned to someone who
    has since been deactivated still names them, the way A4's contention owners
    do. And this is a validation on a WRITE, so a full-form save that re-sends an
    unchanged owner who has since been archived would 404 — hence the
    unchanged-value carve-out in `update_action`.
    """
    if owner_id is None:
        return
    exists = (await db.execute(select(User.id).where(
        User.id == owner_id, User.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(
            status_code=422, detail="owner_id does not reference a user in this tenant")


async def create_action(
    db: AsyncSession, tenant_id: int, finding: PirFinding, data, user_id: Optional[int]
) -> PirAction:
    await _validate_owner(db, tenant_id, data.owner_id)
    action = PirAction(
        tenant_id=tenant_id,
        finding_id=finding.id,
        seq=await _next_action_seq(db, finding.id),
        title=data.title,
        detail=data.detail,
        owner_id=data.owner_id,
        due_date=data.due_date,
        status=data.status,
        created_by=user_id,
    )
    if action.status in CLOSED_ACTION_STATUSES:
        action.closed_at = datetime.now(timezone.utc)
    db.add(action)
    await db.flush()
    return action


async def update_action(db: AsyncSession, tenant_id: int, action_id: int, data) -> PirAction:
    action = await get_action(db, tenant_id, action_id)
    payload = data.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] is None:
        raise HTTPException(status_code=422, detail="title cannot be null")
    # The carve-out: re-sending the owner the row already has is always allowed,
    # so a full-form save never 404s because that user was archived since.
    if "owner_id" in payload and payload["owner_id"] != action.owner_id:
        await _validate_owner(db, tenant_id, payload["owner_id"])
    for key, value in payload.items():
        setattr(action, key, value)
    if action.status in CLOSED_ACTION_STATUSES:
        if action.closed_at is None:
            action.closed_at = datetime.now(timezone.utc)
    else:
        action.closed_at = None
    await db.flush()
    return action


async def delete_action(db: AsyncSession, tenant_id: int, action_id: int) -> None:
    action = await get_action(db, tenant_id, action_id)
    action.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def actions_for_findings(
    db: AsyncSession, tenant_id: int, finding_ids: list[int]
) -> dict[int, list[PirAction]]:
    """One query for a whole PIR, keyed by finding id, `[]` for a finding with none."""
    by_finding: dict[int, list[PirAction]] = {fid: [] for fid in finding_ids}
    if not finding_ids:
        return by_finding
    rows = (await db.execute(select(PirAction).where(
        PirAction.finding_id.in_(finding_ids),
        PirAction.tenant_id == tenant_id,
        PirAction.deleted_at.is_(None),
    ).order_by(PirAction.finding_id, PirAction.seq))).scalars().all()
    for row in rows:
        by_finding[row.finding_id].append(row)
    return by_finding


async def usernames_for(db: AsyncSession, user_ids) -> dict[int, str]:
    """Batched id -> username.

    NOT tenant-qualified, deliberately — the rule A3's `acknowledged_by_username`,
    A4's `usernames_for`, B5's and C2's all follow. Under master-admin
    impersonation an owner can legitimately sit outside the PIR's own tenant, and
    a `User.tenant_id ==` join renders them as nobody: the record losing the one
    name it exists to hold.
    """
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await db.execute(select(User.id, User.username).where(User.id.in_(ids)))).all()
    return {uid: username for uid, username in rows}
```

- [ ] **Step 5: Run the service tests and watch them pass**

Run: `cd backend && uv run pytest tests/services/test_pir_action_service.py -q`
Expected: 10 passed.

- [ ] **Step 6: Prove the day-boundary rule is load-bearing**

Change `is_overdue`'s comparison from `due < expiry_boundary(now)` to `due < now` and confirm `test_an_action_is_overdue_only_after_its_whole_due_day` FAILS. Restore it.

- [ ] **Step 7: Hydrate actions onto the PIR read, and add the routes**

In `backend/app/api/v1/pir.py`, extend `_hydrate` so it builds actions in two queries for the whole PIR — never one per finding:

```python
from datetime import datetime, timezone

from app.api.v1.schemas.pir_finding import PirActionCreate, PirActionResponse, PirActionUpdate


async def _hydrate(db: AsyncSession, tenant_id: int, pir):
    if pir is None:
        return None
    now = datetime.now(timezone.utc)
    findings = await pir_finding_service.findings_for_pir(db, tenant_id, pir.id)
    actions = await pir_finding_service.actions_for_findings(
        db, tenant_id, [f.id for f in findings])
    names = await pir_finding_service.usernames_for(
        db, [a.owner_id for rows in actions.values() for a in rows])

    body = PIRResponse.model_validate(pir).model_dump()
    body["findings"] = []
    for finding in findings:
        item = PirFindingResponse.model_validate(finding).model_dump()
        item["actions"] = [
            {
                **PirActionResponse.model_validate(a).model_dump(
                    exclude={"owner_username", "is_overdue"}),
                "owner_username": names.get(a.owner_id),
                "is_overdue": pir_finding_service.is_overdue(a, now),
            }
            for a in actions[finding.id]
        ]
        body["findings"].append(item)
    return body


@router.post("/{release_id}/pir/findings/{finding_id}/actions",
             response_model=PirActionResponse, status_code=status.HTTP_201_CREATED)
async def create_action(
    release_id: int,
    finding_id: int,
    data: PirActionCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding(db, tenant_id, finding_id)
    action = await pir_finding_service.create_action(db, tenant_id, finding, data, current_user.id)
    return await _action_response(db, action)


@router.patch("/{release_id}/pir/findings/{finding_id}/actions/{action_id}",
              response_model=PirActionResponse)
async def update_action(
    release_id: int,
    finding_id: int,
    action_id: int,
    data: PirActionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    return await _action_response(
        db, await pir_finding_service.update_action(db, tenant_id, action_id, data))


@router.delete("/{release_id}/pir/findings/{finding_id}/actions/{action_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_action(
    release_id: int,
    finding_id: int,
    action_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.delete_action(db, tenant_id, action_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _action_response(db: AsyncSession, action) -> dict:
    """One action rendered the same way `_hydrate` renders it — one definition of
    the row shape, so a POST's response and a later GET's cannot disagree."""
    names = await pir_finding_service.usernames_for(db, [action.owner_id])
    return {
        **PirActionResponse.model_validate(action).model_dump(
            exclude={"owner_username", "is_overdue"}),
        "owner_username": names.get(action.owner_id),
        "is_overdue": pir_finding_service.is_overdue(action, datetime.now(timezone.utc)),
    }
```

- [ ] **Step 8: Add the API tests**

Append to `backend/tests/integration/test_pir_findings_api.py`:

```python
@pytest.mark.asyncio
async def test_an_action_round_trips_on_the_pir_read(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test"})).json()["id"]
    created = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "Add a perf gate", "due_date": "2026-09-30T00:00:00Z"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "open"
    assert created.json()["is_overdue"] is False

    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert [a["title"] for a in body["findings"][0]["actions"]] == ["Add a perf gate"]


@pytest.mark.asyncio
async def test_closing_an_action_names_when_it_closed(authed_client, demo_release_id):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    aid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "T"})).json()["id"]
    resp = await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}",
        json={"status": "done", "closure_note": "gate added"})
    assert resp.status_code == 200
    assert resp.json()["closed_at"] is not None
    assert resp.json()["closure_note"] == "gate added"


@pytest.mark.asyncio
async def test_an_owner_from_another_tenant_is_a_422(authed_client, demo_release_id, db_session):
    """The FK validation, proved by pointing at a user id that exists but is not
    ours — not at an id nobody has."""
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash
    other = Tenant(name="Other Org PIR", slug="other-org-pir")
    db_session.add(other)
    await db_session.flush()
    stranger = User(tenant_id=other.id, username="stranger-pir", email="s@x.test",
                    hashed_password=get_password_hash("password123"), role="Developer")
    db_session.add(stranger)
    await db_session.flush()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "T"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "T", "owner_id": stranger.id})
    assert resp.status_code == 422
```

- [ ] **Step 9: Run everything for this task, both engines**

Run:
```bash
cd backend && uv run pytest tests/services/test_pir_action_service.py \
  tests/integration/test_pir_findings_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_pir_action_service.py tests/integration/test_pir_findings_api.py -q
```
Expected: PASS on both. The PostgreSQL leg is what catches the naive-vs-aware datetime comparison in `is_overdue`.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/pir_finding_service.py backend/app/api/v1/schemas/pir_finding.py \
        backend/app/api/v1/pir.py backend/tests/services/test_pir_action_service.py \
        backend/tests/integration/test_pir_findings_api.py
git commit -m "feat(pir): trackable actions on a finding, with a day-granular overdue rule"
```

---
### Task 4: Incident citations

**Files:**
- Modify: `backend/app/services/pir_finding_service.py`, `backend/app/api/v1/schemas/pir_finding.py`, `backend/app/api/v1/pir.py`
- Test: `backend/tests/services/test_pir_citation_service.py`, add to `backend/tests/integration/test_pir_findings_api.py`

**Interfaces:**
- Consumes: `get_finding` (Task 2), `PirFindingIncident` (Task 1).
- Produces:
  - `pir_finding_service.add_citation(db, tenant_id, finding, incident_id, note) -> PirFindingIncident`
  - `pir_finding_service.remove_citation(db, tenant_id, finding_id, incident_id) -> None`
  - `pir_finding_service.citations_for_findings(db, tenant_id, finding_ids) -> dict[int, list[dict]]` — each `{incident_id, incident_title, severity, status, note}`.
  - `pir_finding_service.citations_for_incident(db, tenant_id, incident_id) -> list[dict]` — each `{pir_id, release_id, release_name, pir_status, finding_id, finding_title, root_cause, action_count, open_action_count, note}`.
  - `pir_finding_service.review_status_for_incidents(db, tenant_id, incident_ids) -> dict[int, str]`.
  - Schema `PirCitationCreate` (`incident_id`, `note`), `PirCitationResponse`; `PirFindingResponse.incidents: list[PirCitationResponse]`.

- [ ] **Step 1: Write the failing service tests**

Create `backend/tests/services/test_pir_citation_service.py`:

```python
"""pir_finding_service — citing an incident as evidence that a process failed.

The PIR fixes the process that let the incident reach production. It does not
fix the incident, and it does not own it.
"""
import pytest
from datetime import datetime, timezone
from fastapi import HTTPException

from app.api.v1.schemas.pir_finding import PirActionCreate, PirFindingCreate
from app.db.models.incident import Incident
from app.services import pir_finding_service

UTC = timezone.utc


async def _incident(db, tenant_id, title="Checkout 500s"):
    inc = Incident(tenant_id=tenant_id, title=title, severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=UTC), source="manual")
    db.add(inc)
    await db.flush()
    return inc


@pytest.mark.asyncio
async def test_citing_twice_is_idempotent_not_a_duplicate(db_session, tenant, user):
    """The citation is a fact, not a counter. Re-citing returns the existing row
    and updates its note rather than raising an IntegrityError at the browser."""
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    first = await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "first")
    second = await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "second")
    assert first.id == second.id
    assert second.note == "second"


@pytest.mark.asyncio
async def test_an_incident_from_another_tenant_cannot_be_cited(db_session, tenant, other_tenant,
                                                               user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    theirs = await _incident(db_session, other_tenant.id, title="Theirs")
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.add_citation(db_session, tenant.id, f, theirs.id, None)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_removing_a_citation_hard_deletes_it(db_session, tenant, user):
    from sqlalchemy import select
    from app.db.models.pir_finding import PirFindingIncident
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await pir_finding_service.remove_citation(db_session, tenant.id, f.id, inc.id)
    rows = (await db_session.execute(select(PirFindingIncident))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_removing_a_citation_that_is_not_there_is_a_404(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    with pytest.raises(HTTPException) as exc:
        await pir_finding_service.remove_citation(db_session, tenant.id, f.id, inc.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_an_incidents_citations_name_the_release_and_count_open_actions(db_session, tenant,
                                                                              user):
    """Every fact the incident page renders travels WITH the row — the release's
    NAME, not its id, and the open-action count, so the reader can see whether
    the process fix is done without opening the release."""
    pir = await _pir(db_session, tenant.id, user.id, name="Release 24.3")
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir,
        PirFindingCreate(kind="went_wrong", title="No load test", root_cause="Gate optional"),
        user.id)
    done = await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="A", status="done"), user.id)
    await pir_finding_service.create_action(
        db_session, tenant.id, f, PirActionCreate(title="B"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, "root incident")

    rows = await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id)
    assert len(rows) == 1
    row = rows[0]
    assert row["release_name"] == "Release 24.3"
    assert row["finding_title"] == "No load test"
    assert row["root_cause"] == "Gate optional"
    assert (row["action_count"], row["open_action_count"]) == (2, 1)
    assert row["pir_status"] == "draft"
    assert row["note"] == "root incident"


@pytest.mark.asyncio
async def test_a_deleted_finding_stops_citing_the_incident(db_session, tenant, user):
    pir = await _pir(db_session, tenant.id, user.id)
    f = await pir_finding_service.create_finding(
        db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
    inc = await _incident(db_session, tenant.id)
    await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await pir_finding_service.delete_finding(db_session, tenant.id, f.id)
    assert await pir_finding_service.citations_for_incident(db_session, tenant.id, inc.id) == []


@pytest.mark.asyncio
async def test_review_status_is_complete_if_any_citing_pir_is_complete(db_session, tenant, user):
    """One incident, two PIRs. 'Reviewed' is answered by the best answer available,
    not by whichever row sorts first."""
    inc = await _incident(db_session, tenant.id)
    for name, status_ in (("R-draft", "draft"), ("R-done", "complete")):
        pir = await _pir(db_session, tenant.id, user.id, name=name)
        pir.status = status_
        f = await pir_finding_service.create_finding(
            db_session, tenant.id, pir, PirFindingCreate(kind="went_wrong", title="T"), user.id)
        await pir_finding_service.add_citation(db_session, tenant.id, f, inc.id, None)
    await db_session.flush()
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {inc.id: "complete"}


@pytest.mark.asyncio
async def test_an_uncited_incident_is_absent_from_the_status_map(db_session, tenant, user):
    """Absent, not 'none' — the caller supplies the default, so one place decides
    what an unreviewed incident is called."""
    inc = await _incident(db_session, tenant.id)
    assert await pir_finding_service.review_status_for_incidents(
        db_session, tenant.id, [inc.id]) == {}
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/services/test_pir_citation_service.py -q`
Expected: FAIL — `AttributeError: module 'app.services.pir_finding_service' has no attribute 'add_citation'`.

- [ ] **Step 3: Add the citation schemas**

Append to `backend/app/api/v1/schemas/pir_finding.py`:

```python
class PirCitationCreate(BaseModel):
    incident_id: int
    note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")


class PirCitationResponse(BaseModel):
    incident_id: int
    incident_title: str
    severity: str
    status: str
    note: Optional[str]
```

Then add `incidents: list[PirCitationResponse] = []` to `PirFindingResponse`.

- [ ] **Step 4: Add the citation service functions**

Append to `backend/app/services/pir_finding_service.py`:

```python
from app.db.models.incident import Incident
from app.db.models.pir_finding import PirFindingIncident
from app.db.models.release import Release


async def add_citation(
    db: AsyncSession, tenant_id: int, finding: PirFinding, incident_id: int, note
) -> PirFindingIncident:
    """Cite an incident as evidence for a finding.

    Idempotent on (finding, incident): the citation is a fact, not a counter, so
    citing twice updates the note and returns the same row rather than surfacing
    `uq_pir_finding_incident` to the browser as a bare 500 — the shape C4's
    rollback-plan revive bug took.
    """
    incident = (await db.execute(select(Incident).where(
        Incident.id == incident_id,
        Incident.tenant_id == tenant_id,
        Incident.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if incident is None:
        raise HTTPException(
            status_code=422,
            detail="incident_id does not reference a valid incident for this tenant",
        )
    existing = (await db.execute(select(PirFindingIncident).where(
        PirFindingIncident.finding_id == finding.id,
        PirFindingIncident.incident_id == incident_id,
    ))).scalar_one_or_none()
    if existing is not None:
        existing.note = note
        await db.flush()
        return existing
    citation = PirFindingIncident(
        tenant_id=tenant_id, finding_id=finding.id, incident_id=incident_id, note=note)
    db.add(citation)
    await db.flush()
    return citation


async def remove_citation(
    db: AsyncSession, tenant_id: int, finding_id: int, incident_id: int
) -> None:
    """Hard delete — removing a citation is a correction, not history."""
    citation = (await db.execute(select(PirFindingIncident).where(
        PirFindingIncident.finding_id == finding_id,
        PirFindingIncident.incident_id == incident_id,
        PirFindingIncident.tenant_id == tenant_id,
    ))).scalar_one_or_none()
    if citation is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    await db.delete(citation)
    await db.flush()


async def citations_for_findings(
    db: AsyncSession, tenant_id: int, finding_ids: list[int]
) -> dict[int, list[dict]]:
    """One query for a whole PIR. The incident's title, severity and status travel
    with the citation — a chip reading `#41` identifies nothing."""
    by_finding: dict[int, list[dict]] = {fid: [] for fid in finding_ids}
    if not finding_ids:
        return by_finding
    rows = (await db.execute(
        select(PirFindingIncident.finding_id, Incident.id, Incident.title, Incident.severity,
               Incident.status, PirFindingIncident.note)
        .join(Incident, Incident.id == PirFindingIncident.incident_id)
        .where(
            PirFindingIncident.finding_id.in_(finding_ids),
            PirFindingIncident.tenant_id == tenant_id,
        )
        .order_by(PirFindingIncident.finding_id, Incident.detected_at.desc(), Incident.id)
    )).all()
    for finding_id, inc_id, title, severity, inc_status, note in rows:
        by_finding[finding_id].append({
            "incident_id": inc_id, "incident_title": title, "severity": severity,
            "status": inc_status, "note": note,
        })
    return by_finding


async def citations_for_incident(
    db: AsyncSession, tenant_id: int, incident_id: int
) -> list[dict]:
    """Everything the incident page renders about the reviews citing it.

    The joins filter `deleted_at` on the finding and the PIR: a review someone
    withdrew is not evidence of anything. The RELEASE join deliberately does not
    — an archived release still renders its name on the citation that references
    it, the read-rendering rule A1 and A2 both settled.
    """
    rows = (await db.execute(
        select(PIR.id, PIR.release_id, Release.name, PIR.status, PirFinding.id,
               PirFinding.title, PirFinding.root_cause, PirFindingIncident.note)
        .join(PirFinding, PirFinding.id == PirFindingIncident.finding_id)
        .join(PIR, PIR.id == PirFinding.pir_id)
        .join(Release, Release.id == PIR.release_id)
        .where(
            PirFindingIncident.incident_id == incident_id,
            PirFindingIncident.tenant_id == tenant_id,
            PirFinding.deleted_at.is_(None),
            PIR.deleted_at.is_(None),
        )
        .order_by(PIR.release_id, PirFinding.seq)
    )).all()
    if not rows:
        return []

    finding_ids = [r[4] for r in rows]
    counts = (await db.execute(
        select(PirAction.finding_id, PirAction.status, func.count())
        .where(PirAction.finding_id.in_(finding_ids), PirAction.deleted_at.is_(None))
        .group_by(PirAction.finding_id, PirAction.status)
    )).all()
    total: dict[int, int] = {}
    open_: dict[int, int] = {}
    for finding_id, action_status, count in counts:
        total[finding_id] = total.get(finding_id, 0) + count
        if action_status in LIVE_ACTION_STATUSES:
            open_[finding_id] = open_.get(finding_id, 0) + count

    return [
        {
            "pir_id": pir_id, "release_id": release_id, "release_name": release_name,
            "pir_status": pir_status, "finding_id": finding_id, "finding_title": finding_title,
            "root_cause": root_cause, "note": note,
            "action_count": total.get(finding_id, 0),
            "open_action_count": open_.get(finding_id, 0),
        }
        for (pir_id, release_id, release_name, pir_status, finding_id, finding_title,
             root_cause, note) in rows
    ]


async def review_status_for_incidents(
    db: AsyncSession, tenant_id: int, incident_ids
) -> dict[int, str]:
    """Batched `{incident_id: 'draft' | 'complete'}` for the incident list column.

    An uncited incident is ABSENT rather than 'none', so the caller decides what
    an unreviewed incident is called and there is one such decision, not two.
    One query for the page — a per-row lookup on a 50-row grid is 50 queries.
    """
    ids = [i for i in incident_ids if i is not None]
    if not ids:
        return {}
    rows = (await db.execute(
        select(PirFindingIncident.incident_id, PIR.status)
        .join(PirFinding, PirFinding.id == PirFindingIncident.finding_id)
        .join(PIR, PIR.id == PirFinding.pir_id)
        .where(
            PirFindingIncident.incident_id.in_(ids),
            PirFindingIncident.tenant_id == tenant_id,
            PirFinding.deleted_at.is_(None),
            PIR.deleted_at.is_(None),
        )
    )).all()
    out: dict[int, str] = {}
    for incident_id, pir_status in rows:
        # complete wins: an incident reviewed to completion anywhere is reviewed.
        if out.get(incident_id) != "complete":
            out[incident_id] = pir_status
    return out
```

- [ ] **Step 5: Run the service tests and watch them pass**

Run: `cd backend && uv run pytest tests/services/test_pir_citation_service.py -q`
Expected: 8 passed.

- [ ] **Step 6: Hydrate citations onto the PIR read and add the two routes**

In `_hydrate` (`backend/app/api/v1/pir.py`), after the actions block, add citations to each finding:

```python
    citations = await pir_finding_service.citations_for_findings(
        db, tenant_id, [f.id for f in findings])
```
and inside the per-finding loop, `item["incidents"] = citations[finding.id]`.

Then the routes:

```python
from app.api.v1.schemas.pir_finding import PirCitationCreate, PirCitationResponse


@router.post("/{release_id}/pir/findings/{finding_id}/incidents",
             response_model=list[PirCitationResponse], status_code=status.HTTP_201_CREATED)
async def cite_incident(
    release_id: int,
    finding_id: int,
    data: PirCitationCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    finding = await pir_finding_service.get_finding(db, tenant_id, finding_id)
    await pir_finding_service.add_citation(db, tenant_id, finding, data.incident_id, data.note)
    return (await pir_finding_service.citations_for_findings(db, tenant_id, [finding_id]))[finding_id]


@router.delete("/{release_id}/pir/findings/{finding_id}/incidents/{incident_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def uncite_incident(
    release_id: int,
    finding_id: int,
    incident_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await pir_finding_service.get_pir_or_404(db, tenant_id, release_id)
    await pir_finding_service.remove_citation(db, tenant_id, finding_id, incident_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 7: Add the API test**

Append to `backend/tests/integration/test_pir_findings_api.py`:

```python
@pytest.mark.asyncio
async def test_citing_an_incident_shows_it_on_the_finding_by_name(authed_client, demo_release_id,
                                                                   db_session, tenant):
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()

    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": inc.id, "note": "root incident"})
    assert resp.status_code == 201, resp.text
    assert resp.json()[0]["incident_title"] == "Checkout 500s"

    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert body["findings"][0]["incidents"][0]["severity"] == "P1"

    assert (await authed_client.delete(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents/{inc.id}"
    )).status_code == 204
    body = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert body["findings"][0]["incidents"] == []
```

- [ ] **Step 8: Run both engines**

Run:
```bash
cd backend && uv run pytest tests/services/test_pir_citation_service.py \
  tests/integration/test_pir_findings_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_pir_citation_service.py tests/integration/test_pir_findings_api.py -q
```
Expected: PASS on both.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/pir_finding_service.py backend/app/api/v1/schemas/pir_finding.py \
        backend/app/api/v1/pir.py backend/tests/services/test_pir_citation_service.py \
        backend/tests/integration/test_pir_findings_api.py
git commit -m "feat(pir): cite an incident as evidence for a went-wrong finding"
```

---
### Task 5: The cross-release action worklist

**Files:**
- Create: `backend/app/api/v1/pir_actions.py`
- Modify: `backend/app/services/pir_finding_service.py`, `backend/app/main.py:155`, `backend/tests/test_sort_whitelist_contract.py`, `frontend/src/constants/sortWhitelists.json`
- Test: `backend/tests/integration/test_pir_actions_worklist.py`

**Interfaces:**
- Consumes: `PirAction`, `PirFinding`, `PIR`, `Release`, `is_overdue`, `usernames_for`, `LIVE_ACTION_STATUSES`.
- Produces:
  - `pir_finding_service.list_actions(db, tenant_id, *, status=None, owner_id=None, overdue=None, release_id=None, incident_id=None, now, page, sort) -> tuple[list[dict], int]`
  - `app.api.v1.pir_actions.PIR_ACTION_SORTS` — `{"due_date", "status", "title", "created_at", "release", "owner"}`
  - `GET /api/v1/pir-actions` returning `list[PirActionRow]` + `X-Total-Count`.
  - `sortWhitelists.json` key `"pir-actions"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_pir_actions_worklist.py` (copy `authed_client`/`demo_release_id` from `tests/integration/test_pir_api.py`; add a second release fixture inline where a test needs two):

```python
"""GET /pir-actions — the page that makes a PIR action a thing someone does.

Actions that live only inside the release tab they were raised in are exactly
the ones nobody does, so every filter here runs in SQL, before the window, and
X-Total-Count describes the FILTERED set.
"""
import pytest


async def _pir_with_action(client, release_id, *, title, **action):
    await client.post(f"/api/v1/releases/{release_id}/pir", json={"summary": "s"})
    fid = (await client.post(f"/api/v1/releases/{release_id}/pir/findings",
                             json={"kind": "went_wrong", "title": "F"})).json()["id"]
    resp = await client.post(f"/api/v1/releases/{release_id}/pir/findings/{fid}/actions",
                             json={"title": title, **action})
    assert resp.status_code == 201, resp.text
    return fid, resp.json()["id"]


@pytest.mark.asyncio
async def test_rows_name_the_release_and_the_finding_not_their_ids(authed_client,
                                                                    demo_release_id):
    await _pir_with_action(authed_client, demo_release_id, title="Add a perf gate")
    resp = await authed_client.get("/api/v1/pir-actions")
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["title"] == "Add a perf gate"
    assert row["release_name"] == "PIR Integration Test Release"
    assert row["finding_title"] == "F"
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_status_filter_runs_in_sql_and_the_total_follows_it(authed_client,
                                                                   demo_release_id):
    fid, aid = await _pir_with_action(authed_client, demo_release_id, title="A")
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
                             json={"title": "B", "status": "done"})
    resp = await authed_client.get("/api/v1/pir-actions?status=open")
    assert [r["title"] for r in resp.json()] == ["A"]
    assert resp.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_no_selection_is_an_omitted_key_not_the_word_all(authed_client, demo_release_id):
    """`all` is buildParams' own sentinel; a vocabulary containing it builds
    byte-identical params for two different states. Four sub-projects have hit
    this. An explicit empty value is a 422, not a silently ignored filter."""
    await _pir_with_action(authed_client, demo_release_id, title="A")
    assert len((await authed_client.get("/api/v1/pir-actions")).json()) == 1
    assert (await authed_client.get("/api/v1/pir-actions?status=")).status_code == 422
    assert (await authed_client.get("/api/v1/pir-actions?status=all")).status_code == 422


@pytest.mark.asyncio
async def test_overdue_filter_uses_the_whole_due_day(authed_client, demo_release_id):
    """Due today is not overdue. The filter and the rendered flag come from one
    clock per request, so a row cannot be selected as overdue and render as not."""
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    fid, _ = await _pir_with_action(
        authed_client, demo_release_id, title="due today",
        due_date=today.isoformat().replace("+00:00", "Z"))
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "due yesterday",
              "due_date": (today - timedelta(days=1)).isoformat().replace("+00:00", "Z")})
    resp = await authed_client.get("/api/v1/pir-actions?overdue=true")
    assert [r["title"] for r in resp.json()] == ["due yesterday"]
    assert resp.json()[0]["is_overdue"] is True


@pytest.mark.asyncio
async def test_a_done_action_past_its_date_is_not_overdue(authed_client, demo_release_id):
    from datetime import datetime, timezone
    fid, aid = await _pir_with_action(
        authed_client, demo_release_id, title="A", due_date="2020-01-01T00:00:00Z")
    await authed_client.patch(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions/{aid}",
        json={"status": "done"})
    assert (await authed_client.get("/api/v1/pir-actions?overdue=true")).json() == []


@pytest.mark.asyncio
async def test_incident_filter_answers_what_is_being_done_about_this_incident(authed_client,
                                                                              demo_release_id,
                                                                              db_session, tenant):
    from datetime import datetime, timezone
    from app.db.models.incident import Incident
    inc = Incident(tenant_id=tenant.id, title="Checkout 500s", severity="P1", status="open",
                   detected_at=datetime(2026, 8, 1, tzinfo=timezone.utc), source="manual")
    db_session.add(inc)
    await db_session.flush()
    fid, _ = await _pir_with_action(authed_client, demo_release_id, title="Add a perf gate")
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": inc.id})
    resp = await authed_client.get(f"/api/v1/pir-actions?incident_id={inc.id}")
    assert [r["title"] for r in resp.json()] == ["Add a perf gate"]
    assert (await authed_client.get(
        f"/api/v1/pir-actions?incident_id={inc.id + 999}")).json() == []


@pytest.mark.asyncio
async def test_an_unknown_sort_by_is_a_422_not_a_silent_fallback(authed_client, demo_release_id):
    await _pir_with_action(authed_client, demo_release_id, title="A")
    assert (await authed_client.get("/api/v1/pir-actions?sort_by=owner_id")).status_code == 422


@pytest.mark.asyncio
async def test_paging_neither_duplicates_nor_drops_a_row_when_due_dates_tie(authed_client,
                                                                            demo_release_id):
    """Every action here shares one due date. Without the id tiebreaker after
    apply_sort, LIMIT/OFFSET returns the same row twice and never returns another."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir/findings",
                                    json={"kind": "went_wrong", "title": "F"})).json()["id"]
    for n in range(6):
        await authed_client.post(
            f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
            json={"title": f"A{n}", "due_date": "2026-09-30T00:00:00Z"})
    seen = []
    for offset in (0, 2, 4):
        page = await authed_client.get(f"/api/v1/pir-actions?limit=2&offset={offset}")
        seen.extend(r["id"] for r in page.json())
    assert len(seen) == 6
    assert len(set(seen)) == 6


@pytest.mark.asyncio
async def test_another_tenants_actions_are_not_in_my_worklist(authed_client, demo_release_id,
                                                              db_session, tenant, user):
    """Mutation check: drop the tenant filter from list_actions and this fails."""
    from app.api.v1.schemas.pir_finding import PirActionCreate, PirFindingCreate
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash
    from app.services import pir_finding_service
    other = Tenant(name="Other Org WL", slug="other-org-wl")
    db_session.add(other)
    await db_session.flush()
    stranger = User(tenant_id=other.id, username="stranger-wl", email="s@wl.test",
                    hashed_password=get_password_hash("password123"), role="Developer")
    db_session.add(stranger)
    await db_session.flush()
    theirs_pir = await _pir(db_session, other.id, stranger.id, name="Theirs")
    theirs_finding = await pir_finding_service.create_finding(
        db_session, other.id, theirs_pir, PirFindingCreate(kind="went_wrong", title="T"),
        stranger.id)
    await pir_finding_service.create_action(
        db_session, other.id, theirs_finding, PirActionCreate(title="Not mine"), stranger.id)
    await db_session.flush()

    await _pir_with_action(authed_client, demo_release_id, title="Mine")
    titles = [r["title"] for r in (await authed_client.get("/api/v1/pir-actions")).json()]
    assert titles == ["Mine"]
```

Copy the `_pir` helper used by the last test from `tests/services/test_pir_finding_service.py`.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/integration/test_pir_actions_worklist.py -q`
Expected: FAIL — 404 on `/api/v1/pir-actions`.

- [ ] **Step 3: Write the worklist query**

Append to `backend/app/services/pir_finding_service.py`:

```python
from app.core.pagination import Page, Sort, apply_sort, fetch_page_rows


async def list_actions(
    db: AsyncSession,
    tenant_id: int,
    *,
    now: datetime,
    status: Optional[str] = None,
    owner_id: Optional[int] = None,
    overdue: Optional[bool] = None,
    release_id: Optional[int] = None,
    incident_id: Optional[int] = None,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
) -> tuple[list[dict], int]:
    """The tenant-wide action worklist.

    Every filter is in SQL, before the window, so `X-Total-Count` describes the
    filtered set rather than the page. `overdue` is expressed with the same day
    boundary `is_overdue` uses, resolved to ONE instant per request and injected
    as a literal — never as dialect date arithmetic, which SQLite and PostgreSQL
    do not agree on closely enough to trust in a query.
    """
    boundary = expiry_boundary(now)
    query = (
        select(PirAction, PirFinding.id, PirFinding.title, PIR.release_id, Release.name,
               PIR.status)
        .join(PirFinding, PirFinding.id == PirAction.finding_id)
        .join(PIR, PIR.id == PirFinding.pir_id)
        .join(Release, Release.id == PIR.release_id)
        .where(
            PirAction.tenant_id == tenant_id,
            PirAction.deleted_at.is_(None),
            PirFinding.deleted_at.is_(None),
            PIR.deleted_at.is_(None),
        )
    )
    if status is not None:
        query = query.where(PirAction.status == status)
    if owner_id is not None:
        query = query.where(PirAction.owner_id == owner_id)
    if release_id is not None:
        query = query.where(PIR.release_id == release_id)
    if incident_id is not None:
        query = query.where(
            select(PirFindingIncident.id)
            .where(
                PirFindingIncident.finding_id == PirFinding.id,
                PirFindingIncident.incident_id == incident_id,
            )
            .exists()
        )
    if overdue is True:
        query = query.where(
            PirAction.due_date.is_not(None),
            PirAction.due_date < boundary,
            PirAction.status.in_(sorted(LIVE_ACTION_STATUSES)),
        )
    elif overdue is False:
        # The exact complement, so true and false PARTITION the set rather than
        # leaving undated and closed actions invisible to both.
        query = query.where(
            (PirAction.due_date.is_(None))
            | (PirAction.due_date >= boundary)
            | (PirAction.status.not_in(sorted(LIVE_ACTION_STATUSES)))
        )

    # apply_sort BEFORE the tiebreaker, never instead of it: due dates and
    # statuses tie constantly, and LIMIT/OFFSET over a partial order duplicates
    # and drops rows across pages.
    query = apply_sort(query, sort).order_by(PirAction.id)
    rows, total = await fetch_page_rows(db, query, page)

    names = await usernames_for(db, [row[0].owner_id for row in rows])
    return [
        {
            "id": action.id,
            "finding_id": finding_id,
            "finding_title": finding_title,
            "release_id": release_id_,
            "release_name": release_name,
            "pir_status": pir_status,
            "title": action.title,
            "detail": action.detail,
            "owner_id": action.owner_id,
            "owner_username": names.get(action.owner_id),
            "due_date": action.due_date,
            "status": action.status,
            "closed_at": action.closed_at,
            "closure_note": action.closure_note,
            "is_overdue": is_overdue(action, now),
        }
        for action, finding_id, finding_title, release_id_, release_name, pir_status in rows
    ], total
```

- [ ] **Step 4: Write the router**

Create `backend/app/api/v1/pir_actions.py`:

```python
"""GET /pir-actions — every PIR action in the tenant, in one place.

A PIR action is a process fix that outlives the release it came from. Inside the
release's own tab it is invisible the moment attention moves on, which is the
classic reason PIR actions never get done. This page is the point of the feature.

Readable by any tenant member, deliberately — the same call the contention and
decommission worklists made. Who may EDIT an action is settled on the PIR, not by
hiding the list.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.pir_finding import PirActionRow
from app.core.pagination import Page, Sort, pagination, set_total_count, sorting
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.pir import PIR
from app.db.models.pir_finding import ACTION_STATUSES, PirAction
from app.db.models.release import Release
from app.db.models.user import User
from app.services import pir_finding_service

router = APIRouter(prefix="/pir-actions", tags=["pir"])

# `release` and `owner` sort by the NAME the row renders, not by the id — sorting
# a column of names by an integer nobody can see is indistinguishable from no
# sort at all. Both are single columns on a joined table, so both are legitimate
# whitelist entries; nothing computed in Python after the query is here.
PIR_ACTION_SORTS = {
    "title": PirAction.title,
    "status": PirAction.status,
    "due_date": PirAction.due_date,
    "created_at": PirAction.created_at,
    "release": Release.name,
    "owner": User.username,
}


@router.get("", response_model=list[PirActionRow])
async def list_pir_actions(
    response: Response,
    status_: Optional[str] = Query(None, alias="status"),
    owner_id: Optional[int] = Query(None),
    overdue: Optional[bool] = Query(None),
    release_id: Optional[int] = Query(None),
    incident_id: Optional[int] = Query(None),
    page: Page = Depends(pagination()),
    sort: Sort = Depends(sorting(PIR_ACTION_SORTS, default="due_date")),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    if status_ is not None and status_ not in ACTION_STATUSES:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=422, detail=f"status must be one of {sorted(ACTION_STATUSES)}")
    rows, total = await pir_finding_service.list_actions(
        db,
        current_user.active_tenant_id,
        now=datetime.now(timezone.utc),
        status=status_,
        owner_id=owner_id,
        overdue=overdue,
        release_id=release_id,
        incident_id=incident_id,
        page=page,
        sort=sort,
    )
    set_total_count(response, total)
    return rows
```

Sorting by `owner` needs the `User` table in the query, so add an outer join in `list_actions` immediately after the `Release` join — an inner join would drop every unowned action the moment someone sorted by owner:

```python
        .outerjoin(User, User.id == PirAction.owner_id)
```

- [ ] **Step 5: Add the row schema**

Append to `backend/app/api/v1/schemas/pir_finding.py`:

```python
class PirActionRow(BaseModel):
    """One worklist row. Every name travels WITH the row — a worklist is a list of
    things the reader has never seen, so an id identifies nothing."""
    id: int
    finding_id: int
    finding_title: str
    release_id: int
    release_name: str
    pir_status: str
    title: str
    detail: Optional[str]
    owner_id: Optional[int]
    owner_username: Optional[str]
    due_date: Optional[datetime]
    status: str
    closed_at: Optional[datetime]
    closure_note: Optional[str]
    is_overdue: bool
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, immediately after line 155 (`app.include_router(pir_router.router, prefix="/api/v1")`):

```python
from app.api.v1 import pir_actions as pir_actions_router
app.include_router(pir_actions_router.router, prefix="/api/v1")
```

- [ ] **Step 7: Run the tests and watch them pass**

Run: `cd backend && uv run pytest tests/integration/test_pir_actions_worklist.py -q`
Expected: 9 passed.

- [ ] **Step 8: Prove the tiebreaker is load-bearing**

Change `apply_sort(query, sort).order_by(PirAction.id)` to `apply_sort(query, sort)` and confirm `test_paging_neither_duplicates_nor_drops_a_row_when_due_dates_tie` FAILS on **PostgreSQL** (SQLite may happen to return insertion order and stay green — that is exactly the class of bug the second engine exists to catch). Restore it.

Run: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/integration/test_pir_actions_worklist.py -q`

- [ ] **Step 9: Register the sort whitelist on both sides**

In `frontend/src/constants/sortWhitelists.json`, add:

```json
  "pir-actions": {
    "sortable": ["title", "status", "due_date", "created_at", "release", "owner"],
    "default": "due_date",
    "default_dir": "asc"
  },
```

In `backend/tests/test_sort_whitelist_contract.py`, import `PIR_ACTION_SORTS` from `app.api.v1.pir_actions` and add to `WHITELISTS`:

```python
    "pir-actions": (PIR_ACTION_SORTS, "due_date", "asc"),
```

- [ ] **Step 10: Run the contract test and the full backend suite, both engines**

Run:
```bash
cd backend && uv run pytest tests/test_sort_whitelist_contract.py -q && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
```
Expected: PASS on both.

- [ ] **Step 11: Commit**

```bash
git add backend/app/api/v1/pir_actions.py backend/app/api/v1/schemas/pir_finding.py \
        backend/app/services/pir_finding_service.py backend/app/main.py \
        backend/tests/integration/test_pir_actions_worklist.py \
        backend/tests/test_sort_whitelist_contract.py frontend/src/constants/sortWhitelists.json
git commit -m "feat(pir): tenant-wide PIR action worklist"
```

---
### Task 6: Backfill the free text, then retire it

**Files:**
- Create: `backend/app/db/migrations/versions/20260829_0930_pirbackfill_retire_pir_free_text.py`
- Create: `backend/tests/test_pir_backfill_migration.py`
- Modify: `backend/app/db/models/pir.py`, `backend/app/api/v1/schemas/pir.py`, `backend/app/services/pir_service.py`, `backend/app/services/incident_service.py:262,266-277`, `backend/app/api/v1/schemas/incident.py:86-92,109,138`, `backend/app/api/v1/incidents.py`, `backend/app/api/v1/pir.py`, `backend/tests/services/test_pir_service.py`, `backend/tests/integration/test_pir_api.py`, `backend/tests/integration/test_incidents_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `PIR` without `incident_id`, `root_cause`, `what_went_well`, `what_went_wrong`, `action_plan`. `IncidentDetail.pir_citations: list[IncidentPirCitation]` replacing `IncidentDetail.pir`. `pir_service.get_for_incident` and `pir_service.pir_status_for_incidents` deleted; callers use `pir_finding_service.citations_for_incident` and `review_status_for_incidents`. Alembic revision `pirbackfill`, down-revision `pirfindings`.

This task is deliberately atomic: the column drop and every consumer of those columns move in one commit, so the tree never holds a half-migrated read model.

- [ ] **Step 1: Write the failing backfill test**

Create `backend/tests/test_pir_backfill_migration.py`. Model it on `tests/test_migration_schema_drift.py` — reuse its `_alembic`, `_scratch_url` and PostgreSQL-availability skip; import them rather than copying if they are module-level, otherwise copy them with a comment saying where from.

```python
"""The `pirbackfill` revision must not lose a word of an existing PIR.

Builds a scratch PostgreSQL database at revision `pirfindings`, inserts legacy
PIR rows covering every combination of free text and incident link, upgrades one
revision, and reads back what the findings tables hold. `alembic downgrade -1`
is never run against the dev database — it steps back from the CURRENT head, not
from your revision.
"""
import pytest
from sqlalchemy import create_engine, text


@pytest.mark.skipif(not _postgres_available(), reason="needs PostgreSQL")
def test_legacy_free_text_becomes_findings_and_actions(scratch_db_at_pirfindings):
    engine = create_engine(_scratch_url("psycopg2"))
    with engine.begin() as conn:
        tenant_id = conn.execute(text(
            "INSERT INTO tenant (name, slug, created_at, updated_at) "
            "VALUES ('T', 't-backfill', now(), now()) RETURNING id")).scalar_one()
        user_id = conn.execute(text(
            "INSERT INTO \"user\" (tenant_id, username, email, hashed_password, role, "
            "is_active, created_at, updated_at) "
            "VALUES (:t, 'u', 'u@x.test', 'x', 'Admin', true, now(), now()) RETURNING id"),
            {"t": tenant_id}).scalar_one()
        tpl_id = conn.execute(text(
            "INSERT INTO lifecycle_template (tenant_id, entity_type, name, is_default, "
            "definition, created_at, updated_at) VALUES (:t, 'release', 'RT', false, "
            "'{\"states\": [], \"transitions\": [], \"field_permissions\": {}}', now(), now()) "
            "RETURNING id"), {"t": tenant_id}).scalar_one()

        def _release(name):
            return conn.execute(text(
                "INSERT INTO release (tenant_id, name, release_type, release_kind, "
                "lifecycle_template_id, status, raised_by, created_at, updated_at) "
                "VALUES (:t, :n, 'Major', 'project', :tpl, 'draft', :u, now(), now()) "
                "RETURNING id"),
                {"t": tenant_id, "n": name, "tpl": tpl_id, "u": user_id}).scalar_one()

        incident_id = conn.execute(text(
            "INSERT INTO incident (tenant_id, title, severity, status, detected_at, source, "
            "created_at, updated_at) VALUES (:t, 'Checkout 500s', 'P1', 'open', now(), "
            "'manual', now(), now()) RETURNING id"), {"t": tenant_id}).scalar_one()

        def _pir(release_id, **cols):
            keys = ", ".join(cols)
            vals = ", ".join(f":{k}" for k in cols)
            return conn.execute(text(
                f"INSERT INTO pir (tenant_id, release_id, status, {keys}, created_at, "
                f"updated_at) VALUES (:t, :r, 'draft', {vals}, now(), now()) RETURNING id"),
                {"t": tenant_id, "r": release_id, **cols}).scalar_one()

        full = _pir(_release("full"), summary="S", root_cause="RC", what_went_well="WW",
                    what_went_wrong="WX", action_plan="AP", incident_id=incident_id)
        text_only = _pir(_release("text-only"), what_went_wrong="WX2")
        incident_only = _pir(_release("incident-only"), incident_id=incident_id)
        well_only = _pir(_release("well-only"), what_went_well="WW3")
        empty = _pir(_release("empty"), summary="just a summary")

    _alembic("pirbackfill")

    with engine.begin() as conn:
        def _findings(pir_id):
            return conn.execute(text(
                "SELECT kind, seq, title, detail, root_cause FROM pir_finding "
                "WHERE pir_id = :p ORDER BY kind, seq"), {"p": pir_id}).all()

        # Everything present: two findings, the action, and the citation.
        rows = _findings(full)
        assert [(r[0], r[2], r[3]) for r in rows] == [
            ("went_well", "What went well (migrated)", "WW"),
            ("went_wrong", "What went wrong (migrated)", "WX"),
        ]
        assert rows[1][4] == "RC"
        assert conn.execute(text(
            "SELECT title, detail, status FROM pir_action a JOIN pir_finding f "
            "ON f.id = a.finding_id WHERE f.pir_id = :p"), {"p": full}).all() == [
            ("Action plan (migrated)", "AP", "open")]
        assert conn.execute(text(
            "SELECT i.incident_id FROM pir_finding_incident i JOIN pir_finding f "
            "ON f.id = i.finding_id WHERE f.pir_id = :p"), {"p": full}).scalar_one() == incident_id

        # A went-wrong finding is created if ANY of the four had a value, so
        # nothing is stranded by the absence of one field.
        assert [r[0] for r in _findings(text_only)] == ["went_wrong"]
        assert [r[2] for r in _findings(incident_only)] == ["Incident (migrated)"]
        assert [r[0] for r in _findings(well_only)] == ["went_well"]

        # A PIR that only ever had a summary migrates to nothing at all.
        assert _findings(empty) == []
        assert conn.execute(text(
            "SELECT summary FROM pir WHERE id = :p"), {"p": empty}).scalar_one() == "just a summary"

        # The columns are gone.
        cols = {r[0] for r in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'pir'")).all()}
        assert cols.isdisjoint(
            {"incident_id", "root_cause", "what_went_well", "what_went_wrong", "action_plan"})
        assert "summary" in cols
```

Add a `scratch_db_at_pirfindings` fixture in the same file that drops and recreates the scratch database and runs `_alembic("pirfindings")`, mirroring what `test_migration_schema_drift.py` already does for `head`.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/test_pir_backfill_migration.py -q`
Expected: FAIL — alembic cannot resolve revision `pirbackfill`. (A `skipped` means PostgreSQL is not running: `docker-compose up -d` and re-run. A skip here proves nothing.)

- [ ] **Step 3: Write the migration**

Create `backend/app/db/migrations/versions/20260829_0930_pirbackfill_retire_pir_free_text.py`:

```python
"""Move a PIR's free text into findings and actions, then drop the columns.

Revision ID: pirbackfill
Revises: pirfindings
Create Date: 2026-08-29 09:30:00.000000

`pir` kept five text columns and a single `incident_id`. A review that found six
things could not say which root cause belonged to which failure, and the link to
an incident was 1:1 in both directions. This moves each PIR's text into the
findings tables `pirfindings` created and then drops the columns.

Titles are FIXED STRINGS ("What went well (migrated)"), never a truncation of
the body: `pir_finding.title` is 500 characters and the free text is unbounded,
so slicing it in would silently lose the tail of a long review.

A went_wrong finding is created if ANY of `what_went_wrong`, `root_cause`,
`action_plan` or `incident_id` held a value, so nothing is stranded by the
absence of one field. A PIR that only ever had a summary migrates to nothing.

DOWNGRADE RE-ADDS THE FIVE COLUMNS AS NULLABLE AND DOES NOT RECONSTRUCT THE
TEXT. The findings rows survive a downgrade; the free text does not come back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'pirbackfill'
down_revision: Union[str, None] = 'pirfindings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(sa.text(
        "SELECT id, tenant_id, created_by, root_cause, what_went_well, what_went_wrong, "
        "action_plan, incident_id FROM pir WHERE deleted_at IS NULL"
    )).mappings().all()

    insert_finding = sa.text(
        "INSERT INTO pir_finding (tenant_id, pir_id, kind, seq, title, detail, root_cause, "
        "created_by, created_at, updated_at) "
        "VALUES (:tenant_id, :pir_id, :kind, 1, :title, :detail, :root_cause, :created_by, "
        "now(), now()) RETURNING id"
    )
    insert_action = sa.text(
        "INSERT INTO pir_action (tenant_id, finding_id, seq, title, detail, status, "
        "created_by, created_at, updated_at) "
        "VALUES (:tenant_id, :finding_id, 1, :title, :detail, 'open', :created_by, now(), now())"
    )
    insert_citation = sa.text(
        "INSERT INTO pir_finding_incident (tenant_id, finding_id, incident_id, created_at, "
        "updated_at) VALUES (:tenant_id, :finding_id, :incident_id, now(), now())"
    )

    def _has_text(value) -> bool:
        return value is not None and str(value).strip() != ""

    for row in rows:
        if _has_text(row["what_went_well"]):
            conn.execute(insert_finding, {
                "tenant_id": row["tenant_id"], "pir_id": row["id"], "kind": "went_well",
                "title": "What went well (migrated)", "detail": row["what_went_well"],
                "root_cause": None, "created_by": row["created_by"],
            })

        needs_wrong = (
            _has_text(row["what_went_wrong"])
            or _has_text(row["root_cause"])
            or _has_text(row["action_plan"])
            or row["incident_id"] is not None
        )
        if not needs_wrong:
            continue

        title = (
            "What went wrong (migrated)"
            if _has_text(row["what_went_wrong"]) or _has_text(row["root_cause"])
            or _has_text(row["action_plan"])
            else "Incident (migrated)"
        )
        finding_id = conn.execute(insert_finding, {
            "tenant_id": row["tenant_id"], "pir_id": row["id"], "kind": "went_wrong",
            "title": title, "detail": row["what_went_wrong"], "root_cause": row["root_cause"],
            "created_by": row["created_by"],
        }).scalar_one()

        if _has_text(row["action_plan"]):
            conn.execute(insert_action, {
                "tenant_id": row["tenant_id"], "finding_id": finding_id,
                "title": "Action plan (migrated)", "detail": row["action_plan"],
                "created_by": row["created_by"],
            })
        if row["incident_id"] is not None:
            conn.execute(insert_citation, {
                "tenant_id": row["tenant_id"], "finding_id": finding_id,
                "incident_id": row["incident_id"],
            })

    op.drop_index("ix_pir_tenant_incident", table_name="pir")
    op.drop_column("pir", "incident_id")
    op.drop_column("pir", "root_cause")
    op.drop_column("pir", "what_went_well")
    op.drop_column("pir", "what_went_wrong")
    op.drop_column("pir", "action_plan")


def downgrade() -> None:
    op.add_column("pir", sa.Column("incident_id", sa.Integer(), nullable=True))
    op.add_column("pir", sa.Column("root_cause", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("what_went_well", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("what_went_wrong", sa.Text(), nullable=True))
    op.add_column("pir", sa.Column("action_plan", sa.Text(), nullable=True))
    op.create_foreign_key("fk_pir_incident_id", "pir", "incident", ["incident_id"], ["id"])
    op.create_index("ix_pir_tenant_incident", "pir", ["tenant_id", "incident_id"])
```

`now()` is used rather than `func.now()` because these are raw `sa.text` statements; both engines accept it.

- [ ] **Step 4: Run the backfill test and watch it pass**

Run: `cd backend && uv run pytest tests/test_pir_backfill_migration.py -q`
Expected: PASS.

- [ ] **Step 5: Update the model and the PIR schemas**

In `backend/app/db/models/pir.py`, delete the five column definitions and the `ix_pir_tenant_incident` index from `__table_args__`, leaving `tenant_id`, `release_id`, `summary`, `status`, `completed_at`, `created_by`, `deleted_at` and `ix_pir_tenant_release`.

In `backend/app/api/v1/schemas/pir.py`, delete `incident_id`, `root_cause`, `what_went_well`, `what_went_wrong` and `action_plan` from `PIRCreate`, `PIRUpdate` and `PIRResponse`, and add `model_config = ConfigDict(extra="forbid")` to `PIRCreate` and `PIRUpdate`. `PIRCreate` keeps `summary` and `status`; `PIRResponse` keeps `id`, `release_id`, `summary`, `status`, `completed_at`, `findings`.

- [ ] **Step 6: Update `pir_service`**

In `backend/app/services/pir_service.py`: delete `_validate_incident`, delete `get_for_incident`, delete `pir_status_for_incidents`, and drop `incident_id` from `create_for_release` and from `update`'s payload handling. `create_for_release` becomes:

```python
    pir = PIR(
        tenant_id=tenant_id, release_id=release_id, summary=data.summary,
        status=data.status or "draft", created_by=user_id,
    )
```

Add a module docstring line recording why the incident link left:

```python
"""One PIR per release: a summary and a status.

Everything the review FOUND lives in `pir_finding_service`. `PIR.incident_id`
was a single nullable FK read with `scalar_one_or_none`, making the incident
relationship 1:1 in both directions; it is now a many-to-many citation against a
went-wrong finding, because one incident often exposes two distinct process
failures and one failure often produces a run of incidents.
"""
```

- [ ] **Step 7: Update the incident read model**

In `backend/app/api/v1/schemas/incident.py`, replace `IncidentPirRef` with:

```python
class IncidentPirCitation(BaseModel):
    """One review that cites this incident as evidence.

    The PIR fixes the process that let the incident reach production; it does
    not fix the incident. `open_action_count` is here so the reader can see
    whether the process fix is still outstanding without opening the release.
    """
    pir_id: int
    release_id: int
    release_name: str
    pir_status: str
    finding_id: int
    finding_title: str
    root_cause: Optional[str] = None
    note: Optional[str] = None
    action_count: int
    open_action_count: int
```

and change `IncidentDetail`'s `pir: Optional[IncidentPirRef] = None` to:

```python
    pir_citations: list[IncidentPirCitation] = []
```

`IncidentListRow.pir_status` keeps its name and its `none`/`draft`/`complete` vocabulary.

- [ ] **Step 8: Update `incident_service` and the incidents router**

In `backend/app/services/incident_service.py`, replace `_pir_ref` with a call through the new service, and change the detail builder's key:

```python
        "pir_citations": await pir_finding_service.citations_for_incident(db, tenant_id, inc.id),
```

Delete `_pir_ref` entirely, and change the `pir_service` import to `pir_finding_service`.

In `backend/app/api/v1/incidents.py`, wherever `pir_service.pir_status_for_incidents` is called for the list, call `pir_finding_service.review_status_for_incidents` instead — same signature, same batched shape, and the `"none"` default stays at the call site (`statuses.get(inc.id, "none")`).

- [ ] **Step 9: Route the PIR create/update responses through `_hydrate`**

In `backend/app/api/v1/pir.py`, `create_pir` and `update_pir` currently return the bare model. Wrap both, so every route returns one shape:

```python
    return await _hydrate(db, tenant_id, await pir_service.create_for_release(
        db, tenant_id, release_id, data, current_user.id))
```

- [ ] **Step 10: Update the existing PIR and incident tests**

`tests/services/test_pir_service.py` and `tests/integration/test_pir_api.py` assert on the five removed fields. Rewrite each such assertion against findings — e.g. a test that created a PIR with `what_went_wrong="x"` now creates the PIR and then a `went_wrong` finding, and asserts on `body["findings"]`. Delete tests that only ever exercised `incident_id` on the PIR; the citation path replaces them and is covered by Task 4. In `tests/integration/test_incidents_api.py`, change every `body["pir"]` assertion to `body["pir_citations"]`.

Do **not** delete a test because it is inconvenient — if a rule it pinned still holds, it must still be pinned somewhere.

- [ ] **Step 11: Apply to the dev database and run everything, both engines**

Run:
```bash
cd backend
uv run alembic upgrade head && uv run alembic current   # expect pirbackfill (head)
uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
uv run pytest tests/test_migration_schema_drift.py -q
```
Expected: PASS on all. The drift test compares column NAME SETS only — it will catch the dropped columns being absent from one side and not the other, and it will not catch a type or index difference, so do not read its pass as proof the DDL matches the models.

- [ ] **Step 12: Commit**

```bash
git add backend/app/db/migrations/versions/20260829_0930_pirbackfill_retire_pir_free_text.py \
        backend/app/db/models/pir.py backend/app/api/v1/schemas/pir.py \
        backend/app/api/v1/schemas/incident.py backend/app/api/v1/pir.py \
        backend/app/api/v1/incidents.py backend/app/services/pir_service.py \
        backend/app/services/incident_service.py backend/tests/
git commit -m "feat(pir)!: retire the PIR free-text columns and the 1:1 incident link"
```

---
### Task 7: The implemented-release filter and the composite citation endpoint

**Files:**
- Modify: `backend/app/services/release_service.py:247-268`, `backend/app/api/v1/releases.py:191-207`, `backend/app/api/v1/incidents.py`, `backend/app/api/v1/schemas/incident.py`
- Create: `backend/tests/integration/test_incident_pir_citation_api.py`
- Test: add to `backend/tests/integration/test_releases_api.py`

**Interfaces:**
- Consumes: `pir_service.create_for_release`, `pir_finding_service.{get_pir_or_404, create_finding, create_action, add_citation, citations_for_incident}`.
- Produces:
  - `GET /releases?implemented=true` — `COALESCE(actual_date, target_date) <= now`.
  - `POST /incidents/{incident_id}/pir-citation` taking `IncidentPirCitationRequest` and returning `list[IncidentPirCitation]`.

- [ ] **Step 1: Write the failing filter test**

Append to `backend/tests/integration/test_releases_api.py`:

```python
@pytest.mark.asyncio
async def test_implemented_filter_offers_only_releases_that_have_gone_live(client, auth_headers,
                                                                           db_session,
                                                                           test_tenant):
    """A release that has not gone live cannot have caused a production incident,
    so the incident page's release picker never offers one.

    COALESCE(actual_date, target_date): plenty of releases here never get an
    actual date recorded, and excluding those would leave the picker empty on
    real data. A release with neither date is excluded — nothing says it shipped.
    """
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    # Create four releases directly: shipped (actual in the past), planned-past
    # (target in the past, no actual), future (target ahead), undated.
    ...  # follow this file's existing release-creation helper
    resp = await client.get("/api/v1/releases?implemented=true", headers=auth_headers)
    names = {r["name"] for r in resp.json()}
    assert names == {"shipped", "planned-past"}
    assert "future" not in names and "undated" not in names


@pytest.mark.asyncio
async def test_omitting_implemented_filters_nothing(client, auth_headers):
    """No selection is an OMITTED KEY. `?implemented=` is a 422, never an ignored
    param — FastAPI drops unknown params silently and this codebase has shipped
    that bug three times."""
    all_names = {r["name"] for r in (await client.get(
        "/api/v1/releases", headers=auth_headers)).json()}
    assert "future" in all_names
    assert (await client.get("/api/v1/releases?implemented=",
                             headers=auth_headers)).status_code == 422
```

Replace the `...` with this file's existing pattern for creating releases (read the top of the file first — it may use `post_release`-style helpers or direct model construction).

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/integration/test_releases_api.py -k implemented -q`
Expected: FAIL — the filter is ignored, so `future` and `undated` come back.

- [ ] **Step 3: Add the filter**

In `backend/app/services/release_service.py`, add `implemented: Optional[bool] = None` to `list_releases`' keyword arguments, and after the existing filters:

```python
    if implemented is not None:
        # "Past its implementation date": the actual date if one was recorded,
        # otherwise the planned one. A release with neither is excluded — nothing
        # about it says it shipped. `now` is resolved once per request and
        # compared as a literal, never through dialect date arithmetic.
        moment = now or datetime.now(timezone.utc)
        went_live = func.coalesce(Release.actual_date, Release.target_date)
        base_where.append(went_live <= moment if implemented else
                          sa.or_(went_live > moment, went_live.is_(None)))
```

In `backend/app/api/v1/releases.py`, add the query parameter to `list_releases` and pass it through:

```python
    implemented: Optional[bool] = Query(
        None,
        description="Only releases past their implementation date "
                    "(COALESCE(actual_date, target_date) <= now). Omit for no filter.",
    ),
```

- [ ] **Step 4: Run the filter tests and watch them pass**

Run: `cd backend && uv run pytest tests/integration/test_releases_api.py -q`
Expected: PASS, including every pre-existing test in the file — a new filter that changes the unfiltered page is a regression.

- [ ] **Step 5: Write the failing composite-endpoint tests**

Create `backend/tests/integration/test_incident_pir_citation_api.py` (copy `authed_client`/`demo_release_id` from `tests/integration/test_pir_api.py`, plus an `incident` fixture inserting an `Incident` in the same tenant):

```python
"""POST /incidents/{id}/pir-citation — the journey this feature exists for.

Choose a release that has gone live, then either cite an existing finding or
create one. If that release has no PIR yet, it is created as part of the
citation. Nothing here prompts creating a RELEASE, and nothing asks for a fix
release.
"""
import pytest


@pytest.mark.asyncio
async def test_citing_creates_the_pir_the_finding_and_the_action_in_one_call(authed_client,
                                                                             demo_release_id,
                                                                             incident):
    """One transaction. `get_db` commits per request, so three separate calls
    would leave a PIR behind with no citation on it when the second failed."""
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={
            "release_id": demo_release_id,
            "new_finding": {
                "title": "No load test before go-live",
                "detail": "Perf suite is opt-in",
                "root_cause": "The perf gate is optional on this template",
                "actions": [{"title": "Make the perf gate mandatory for Tier 1"}],
            },
            "note": "root incident",
        },
    )
    assert resp.status_code == 201, resp.text
    citations = resp.json()
    assert len(citations) == 1
    assert citations[0]["finding_title"] == "No load test before go-live"
    assert citations[0]["open_action_count"] == 1

    pir = (await authed_client.get(f"/api/v1/releases/{demo_release_id}/pir")).json()
    assert pir is not None
    assert pir["findings"][0]["incidents"][0]["incident_id"] == incident.id


@pytest.mark.asyncio
async def test_citing_an_existing_finding_adds_no_second_pir(authed_client, demo_release_id,
                                                              incident):
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "Existing"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 201
    assert resp.json()[0]["finding_id"] == fid


@pytest.mark.asyncio
async def test_both_or_neither_is_a_422(authed_client, demo_release_id, incident):
    both = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": 1,
              "new_finding": {"title": "T"}})
    assert both.status_code == 422
    neither = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id})
    assert neither.status_code == 422


@pytest.mark.asyncio
async def test_a_release_with_no_recorded_actual_date_is_still_citable(authed_client,
                                                                       demo_release_id, incident):
    """`implemented` is a PICKER FILTER, a helper for choosing well — not a rule
    about what a PIR may be attached to. A release whose actual date nobody
    recorded must not become unreviewable."""
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "new_finding": {"title": "T"}})
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_a_finding_belonging_to_another_release_is_a_422(authed_client, demo_release_id,
                                                                other_release_id, incident):
    """A finding id from a different release must not silently attach the citation
    to the wrong review."""
    await authed_client.post(f"/api/v1/releases/{other_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{other_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "Elsewhere"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_citing_a_went_well_finding_is_refused(authed_client, demo_release_id, incident):
    """An incident is evidence that something went WRONG. Citing it against a
    'keep doing this' item would put a production failure in the good column."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_well", "title": "Canary caught it"})).json()["id"]
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": demo_release_id, "finding_id": fid})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_a_release_in_another_tenant_is_a_404(authed_client, incident, foreign_release_id):
    resp = await authed_client.post(
        f"/api/v1/incidents/{incident.id}/pir-citation",
        json={"release_id": foreign_release_id, "new_finding": {"title": "T"}})
    assert resp.status_code == 404
```

Add `other_release_id` and `foreign_release_id` fixtures in the same file, built the same way `demo_release_id` is (the foreign one under a second `Tenant`).

- [ ] **Step 6: Run them and watch them fail**

Run: `cd backend && uv run pytest tests/integration/test_incident_pir_citation_api.py -q`
Expected: FAIL — 404/405 on the route.

- [ ] **Step 7: Add the request schema**

Append to `backend/app/api/v1/schemas/incident.py`:

```python
from app.api.v1.schemas.pir_finding import PirActionCreate, PirFindingCreate


class IncidentPirNewFinding(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    detail: Optional[str] = None
    root_cause: Optional[str] = None
    actions: list[PirActionCreate] = []
    model_config = ConfigDict(extra="forbid")


class IncidentPirCitationRequest(BaseModel):
    """Cite this incident on a release's PIR.

    Exactly one of `finding_id` / `new_finding`. Both, or neither, is a 422 —
    a request that says two things is a bug in the caller, and guessing which one
    it meant is how a citation lands on the wrong review.

    The finding kind is not a parameter: an incident is evidence that something
    went WRONG, so a created finding is always `went_wrong` and an existing one
    must be.
    """
    release_id: int
    finding_id: Optional[int] = None
    new_finding: Optional[IncidentPirNewFinding] = None
    note: Optional[str] = None
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.finding_id is None) == (self.new_finding is None):
            raise ValueError("supply exactly one of finding_id or new_finding")
        return self
```

Import `Field` and `model_validator` from pydantic at the top of the file if they are not already there.

- [ ] **Step 8: Add the endpoint**

In `backend/app/api/v1/incidents.py`:

```python
@router.post("/{incident_id}/pir-citation", response_model=list[IncidentPirCitation],
             status_code=status.HTTP_201_CREATED)
async def cite_incident_on_a_pir(
    incident_id: int,
    data: IncidentPirCitationRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Cite this incident as evidence on a release's PIR, creating what is missing.

    ONE TRANSACTION, deliberately. The dialog would otherwise make up to three
    calls, and `get_db` commits per request: a failure on call two leaves a PIR
    behind that nobody asked for, with no citation on it.

    `release_id` is validated as a live release in this tenant. It is NOT
    validated as implemented — `?implemented=true` is a picker filter, a helper
    for choosing well, not a rule about what a PIR may be attached to.
    """
    tenant_id = current_user.active_tenant_id
    incident = await incident_service.get_incident_or_404(db, incident_id, tenant_id)

    pir = await pir_service.get_for_release(db, tenant_id, data.release_id)
    if pir is None:
        pir = await pir_service.create_for_release(
            db, tenant_id, data.release_id, PIRCreate(), current_user.id)

    if data.finding_id is not None:
        finding = await pir_finding_service.get_finding(db, tenant_id, data.finding_id)
        if finding.pir_id != pir.id:
            raise HTTPException(
                status_code=422, detail="finding_id does not belong to that release's PIR")
        if finding.kind != "went_wrong":
            raise HTTPException(
                status_code=422,
                detail="an incident is evidence of something going wrong; "
                       "cite it against a went_wrong finding",
            )
    else:
        finding = await pir_finding_service.create_finding(
            db, tenant_id, pir,
            PirFindingCreate(
                kind="went_wrong",
                title=data.new_finding.title,
                detail=data.new_finding.detail,
                root_cause=data.new_finding.root_cause,
            ),
            current_user.id,
        )
        for action in data.new_finding.actions:
            await pir_finding_service.create_action(
                db, tenant_id, finding, action, current_user.id)

    await pir_finding_service.add_citation(db, tenant_id, finding, incident.id, data.note)
    return await pir_finding_service.citations_for_incident(db, tenant_id, incident.id)
```

`pir_service.create_for_release` validates the release against the tenant and 404s, which is what makes the foreign-release test pass. If `incident_service` has no `get_incident_or_404`, use whatever the existing detail route uses to fetch and 404 an incident — do not add a second lookup rule.

- [ ] **Step 9: Run the tests and watch them pass**

Run: `cd backend && uv run pytest tests/integration/test_incident_pir_citation_api.py -q`
Expected: 7 passed.

- [ ] **Step 10: Both engines, whole suite**

Run:
```bash
cd backend && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
```
Expected: PASS on both.

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/release_service.py backend/app/api/v1/releases.py \
        backend/app/api/v1/incidents.py backend/app/api/v1/schemas/incident.py \
        backend/tests/integration/test_incident_pir_citation_api.py \
        backend/tests/integration/test_releases_api.py
git commit -m "feat(pir): cite an incident from the incident page, on a release that went live"
```

---
### Task 8: The named guard — this work refuses nothing

**Files:**
- Create: `backend/tests/test_pir_records_never_refuses.py`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: nothing. This task adds no production code. If it ever needs production code to pass, something has started refusing.

The sixth sub-project running whose central promise is a named test rather than an absence in the diff — after A3, A4, B2, B4, C2 and C4. Model this file on `backend/tests/test_c4_records_never_refuses.py`: read it first for the fixture shape and the docstring conventions.

- [ ] **Step 1: Write the guard**

Create `backend/tests/test_pir_records_never_refuses.py`:

```python
"""PIR FINDINGS, ACTIONS AND CITATIONS RECORD. THEY REFUSE NOTHING.

A PIR is written after go-live, about a release people already consider
finished. Nothing here may block a release transition, an incident transition, a
deployment, or a booking — not an incomplete PIR, not a went-wrong finding, not
an overdue open action, not a cited incident.

requirements.md 2.5 asks for a configurable "PIR complete" gate before a release
is formally closed. That is deliberately NOT built (see the spec, section 9), and
this file is what will fail the day someone builds it here by accident.

IF ANY TEST IN THIS FILE FAILS, THE PIR WORK HAS STARTED REFUSING SOMETHING.

Proved non-vacuous — see the last step of Task 8 in the plan: inserting a real
refusal into the release transition path makes
`test_a_release_with_an_overdue_action_still_transitions` fail, and removing it
again makes it pass. A guard nobody has watched fail is a guard nobody knows
works.
"""
import pytest
from datetime import datetime, timezone

UTC = timezone.utc


@pytest.fixture
async def release_with_a_bad_pir(authed_client, demo_release_id, incident):
    """A release whose review is as damning as this feature can make it:
    incomplete, a went-wrong finding, an overdue open action, a cited incident."""
    await authed_client.post(f"/api/v1/releases/{demo_release_id}/pir", json={"summary": "s"})
    fid = (await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings",
        json={"kind": "went_wrong", "title": "No load test",
              "root_cause": "Perf gate optional"})).json()["id"]
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/actions",
        json={"title": "Make the perf gate mandatory", "due_date": "2020-01-01T00:00:00Z"})
    await authed_client.post(
        f"/api/v1/releases/{demo_release_id}/pir/findings/{fid}/incidents",
        json={"incident_id": incident.id})
    return demo_release_id


@pytest.mark.asyncio
async def test_the_fixture_really_is_as_bad_as_it_claims(authed_client, release_with_a_bad_pir):
    """Guards the guard. If the fixture stops producing an overdue open action on
    an incomplete PIR, every test below passes while testing nothing."""
    body = (await authed_client.get(f"/api/v1/releases/{release_with_a_bad_pir}/pir")).json()
    assert body["status"] == "draft"
    action = body["findings"][0]["actions"][0]
    assert action["status"] == "open"
    assert action["is_overdue"] is True
    assert body["findings"][0]["incidents"] != []


@pytest.mark.asyncio
async def test_a_release_with_an_overdue_action_still_transitions(authed_client,
                                                                   release_with_a_bad_pir):
    """The allowed transitions are byte-identical to what they were before the PIR
    existed — not merely non-empty."""
    before = (await authed_client.get(
        f"/api/v1/releases/{release_with_a_bad_pir}/allowed-transitions")).json()
    # ... create the PIR content via the fixture (already done), then re-read
    after = (await authed_client.get(
        f"/api/v1/releases/{release_with_a_bad_pir}/allowed-transitions")).json()
    assert after == before
    assert after != []


@pytest.mark.asyncio
async def test_the_cited_incident_still_transitions(authed_client, release_with_a_bad_pir,
                                                    incident):
    resp = await authed_client.get(f"/api/v1/incidents/{incident.id}")
    assert resp.json()["allowed_transitions"] != []
    assert resp.json()["pir_citations"] != []


@pytest.mark.asyncio
async def test_can_deploy_is_untouched(authed_client, release_with_a_bad_pir, api_key_headers,
                                       client):
    """`GET /webhooks/can-deploy` is what a pipeline obeys. A PIR is written after
    the deployment it reviews; it cannot retroactively refuse one."""
    resp = await client.get(
        f"/api/v1/webhooks/can-deploy?release_id={release_with_a_bad_pir}",
        headers=api_key_headers)
    assert resp.status_code == 200
    assert resp.json()["can_deploy"] is not False or "pir" not in str(resp.json()).lower()


@pytest.mark.asyncio
async def test_the_readiness_verdict_says_nothing_about_pirs(authed_client,
                                                              release_with_a_bad_pir):
    """C2 and C4's verdict is read BEFORE a release goes live. A finding written
    afterwards must not appear in it — not as a blocker and not as a warning."""
    body = (await authed_client.get(
        f"/api/v1/releases/{release_with_a_bad_pir}/readiness")).json()
    blob = str(body).lower()
    assert "pir" not in blob
    assert "post-implementation" not in blob


@pytest.mark.asyncio
async def test_an_incident_with_no_citation_is_still_fully_usable(authed_client, incident):
    """Nothing anywhere requires an incident to be reviewed. The absence of a
    citation is an ordinary state, not a gap to be closed."""
    resp = await authed_client.get(f"/api/v1/incidents/{incident.id}")
    assert resp.json()["pir_citations"] == []
    assert resp.json()["allowed_transitions"] != []


@pytest.mark.asyncio
async def test_completing_a_pir_moves_nothing_on_the_release(authed_client,
                                                              release_with_a_bad_pir):
    """The other direction: a COMPLETE review does not advance anything either.
    Recording is not deciding."""
    before = (await authed_client.get(f"/api/v1/releases/{release_with_a_bad_pir}")).json()
    await authed_client.patch(f"/api/v1/releases/{release_with_a_bad_pir}/pir",
                              json={"status": "complete"})
    after = (await authed_client.get(f"/api/v1/releases/{release_with_a_bad_pir}")).json()
    assert after["status"] == before["status"]
    assert after["actual_date"] == before["actual_date"]
```

Fix up the endpoint paths against the real routers as you go — `allowed-transitions`, `readiness` and `can-deploy` all exist, but check their exact spelling in `backend/app/api/v1/releases.py` and `backend/app/api/v1/webhooks.py` rather than trusting these strings. The `api_key_headers` fixture exists in the webhook tests; reuse it, and if the `can-deploy` shape makes the assertion above awkward, assert instead that the response is byte-identical with and without the PIR content — that is the claim, stated more directly.

- [ ] **Step 2: Run it**

Run: `cd backend && uv run pytest tests/test_pir_records_never_refuses.py -q`
Expected: 7 passed.

- [ ] **Step 3: Prove it is non-vacuous — this step is the point of the task**

Temporarily insert a real refusal into the release transition path, in `backend/app/services/release_service.py`'s transition validation:

```python
    # TEMPORARY — remove after proving the guard fails
    from app.services import pir_finding_service
    rows, _ = await pir_finding_service.list_actions(
        db, tenant_id, now=datetime.now(timezone.utc), overdue=True, release_id=release.id)
    if rows:
        raise HTTPException(status_code=409, detail="PIR actions are overdue")
```

Run the file again and confirm `test_a_release_with_an_overdue_action_still_transitions` **FAILS**. Then remove the block and confirm the file passes again. Record in the commit message that this was done — A1, A4, B4, B5 and B6 each took this step, and it is why those guards are trusted.

- [ ] **Step 4: Both engines**

Run:
```bash
cd backend && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
```
Expected: PASS on both.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pir_records_never_refuses.py
git commit -m "test(pir): the guard on the promise — PIR content refuses nothing

Proved non-vacuous by inserting a 409 on overdue actions into the release
transition path and watching test_a_release_with_an_overdue_action_still_
transitions fail, then removing it again."
```

---
### Task 9: Frontend types and service layer

**Files:**
- Modify: `frontend/src/types/pir.ts`, `frontend/src/types/incident.ts:15,30`, `frontend/src/services/pirService.ts`, `frontend/src/services/incidentService.ts`, `frontend/src/services/releaseService.ts`
- Test: `frontend/src/services/__tests__/pirService.test.ts`

**Interfaces:**
- Consumes: the backend shapes from Tasks 2–7.
- Produces:
  - Types `PirFinding`, `PirAction`, `PirCitation`, `PirActionRow`, `IncidentPirCitation`, and a `PIR` without the five retired fields.
  - `pirService.{getForRelease, create, update, remove, createFinding, updateFinding, deleteFinding, createAction, updateAction, deleteAction, citeIncident, unciteIncident, listActions}`.
  - `incidentService.citeOnPir(incidentId, body)`.
  - `releaseService.list({ implemented: true })` — verify the existing `list` already forwards arbitrary params before adding anything.

- [ ] **Step 1: Write the failing service test**

Create `frontend/src/services/__tests__/pirService.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import api from '../api';
import { pirService } from '../pirService';

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const mockedApi = api as unknown as {
  get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn>;
};

beforeEach(() => vi.resetAllMocks());

describe('pirService', () => {
  it('creates a finding under its release', async () => {
    mockedApi.post.mockResolvedValue({ data: { id: 7 } });
    await pirService.createFinding(3, { kind: 'went_wrong', title: 'T' });
    expect(mockedApi.post).toHaveBeenCalledWith('/releases/3/pir/findings',
      { kind: 'went_wrong', title: 'T' });
  });

  it('cites an incident against a finding', async () => {
    mockedApi.post.mockResolvedValue({ data: [] });
    await pirService.citeIncident(3, 7, { incident_id: 41, note: 'n' });
    expect(mockedApi.post).toHaveBeenCalledWith('/releases/3/pir/findings/7/incidents',
      { incident_id: 41, note: 'n' });
  });

  it('uncites by incident id, not by a citation id', async () => {
    mockedApi.delete.mockResolvedValue({ data: null });
    await pirService.unciteIncident(3, 7, 41);
    expect(mockedApi.delete).toHaveBeenCalledWith('/releases/3/pir/findings/7/incidents/41');
  });

  it('reads the worklist total off X-Total-Count, not off the page length', async () => {
    mockedApi.get.mockResolvedValue({ data: [{ id: 1 }], headers: { 'x-total-count': '97' } });
    const { rows, total } = await pirService.listActions({ limit: 1, offset: 0 });
    expect(rows).toHaveLength(1);
    expect(total).toBe(97);
  });

  it('falls back to the page length when the header is missing', async () => {
    mockedApi.get.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: {} });
    expect((await pirService.listActions({})).total).toBe(2);
  });
});
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npm run test -- src/services/__tests__/pirService.test.ts`
Expected: FAIL — `pirService.createFinding is not a function`.

- [ ] **Step 3: Rewrite the types**

Replace `frontend/src/types/pir.ts` entirely:

```ts
export type PirStatus = 'draft' | 'complete';
export type PirFindingKind = 'went_well' | 'went_wrong';
export type PirActionStatus = 'open' | 'in_progress' | 'done' | 'cancelled';

export interface PirCitation {
  incident_id: number;
  incident_title: string;
  severity: string;
  status: string;
  note: string | null;
}

export interface PirAction {
  id: number;
  finding_id: number;
  seq: number;
  title: string;
  detail: string | null;
  owner_id: number | null;
  /** Resolved server-side and travelling with the row — never looked up here. */
  owner_username: string | null;
  due_date: string | null;
  status: PirActionStatus;
  closed_at: string | null;
  closure_note: string | null;
  /** The server's verdict, from one clock per request. Never re-derived here:
   *  a browser with a wrong clock would otherwise manufacture overdue rows. */
  is_overdue: boolean;
}

export interface PirFinding {
  id: number;
  kind: PirFindingKind;
  seq: number;
  title: string;
  detail: string | null;
  root_cause: string | null;
  created_at: string;
  actions: PirAction[];
  incidents: PirCitation[];
}

export interface PIR {
  id: number;
  release_id: number;
  summary: string | null;
  status: PirStatus;
  completed_at: string | null;
  findings: PirFinding[];
}

export interface PIRWrite {
  summary?: string | null;
  status?: PirStatus;
}

export interface PirFindingWrite {
  kind?: PirFindingKind;
  title?: string;
  detail?: string | null;
  root_cause?: string | null;
}

export interface PirActionWrite {
  title?: string;
  detail?: string | null;
  owner_id?: number | null;
  due_date?: string | null;
  status?: PirActionStatus;
  closure_note?: string | null;
}

/** One row of the cross-release worklist. */
export interface PirActionRow extends PirAction {
  finding_title: string;
  release_id: number;
  release_name: string;
  pir_status: PirStatus;
}
```

In `frontend/src/types/incident.ts`, replace line 30's `pir` field with:

```ts
  pir_citations: IncidentPirCitation[];
```

and add:

```ts
export interface IncidentPirCitation {
  pir_id: number;
  release_id: number;
  release_name: string;
  pir_status: 'draft' | 'complete';
  finding_id: number;
  finding_title: string;
  root_cause: string | null;
  note: string | null;
  action_count: number;
  open_action_count: number;
}
```

Line 15's `pir_status` keeps its three-value union unchanged.

- [ ] **Step 4: Extend the services**

Replace `frontend/src/services/pirService.ts`:

```ts
import api from './api';
import type { Paged } from '../types/pagination';
import type {
  PIR, PIRWrite, PirAction, PirActionRow, PirActionWrite, PirCitation, PirFinding,
  PirFindingWrite,
} from '../types/pir';

export const pirService = {
  getForRelease: (releaseId: number) =>
    api.get<PIR | null>(`/releases/${releaseId}/pir`).then((r) => r.data),
  create: (releaseId: number, data: PIRWrite) =>
    api.post<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  update: (releaseId: number, data: PIRWrite) =>
    api.patch<PIR>(`/releases/${releaseId}/pir`, data).then((r) => r.data),
  remove: (releaseId: number) => api.delete(`/releases/${releaseId}/pir`).then((r) => r.data),

  createFinding: (releaseId: number, data: PirFindingWrite) =>
    api.post<PirFinding>(`/releases/${releaseId}/pir/findings`, data).then((r) => r.data),
  updateFinding: (releaseId: number, findingId: number, data: PirFindingWrite) =>
    api.patch<PirFinding>(`/releases/${releaseId}/pir/findings/${findingId}`, data)
      .then((r) => r.data),
  deleteFinding: (releaseId: number, findingId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}`).then((r) => r.data),

  createAction: (releaseId: number, findingId: number, data: PirActionWrite) =>
    api.post<PirAction>(`/releases/${releaseId}/pir/findings/${findingId}/actions`, data)
      .then((r) => r.data),
  updateAction: (releaseId: number, findingId: number, actionId: number, data: PirActionWrite) =>
    api.patch<PirAction>(
      `/releases/${releaseId}/pir/findings/${findingId}/actions/${actionId}`, data)
      .then((r) => r.data),
  deleteAction: (releaseId: number, findingId: number, actionId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}/actions/${actionId}`)
      .then((r) => r.data),

  citeIncident: (releaseId: number, findingId: number,
                 data: { incident_id: number; note?: string | null }) =>
    api.post<PirCitation[]>(`/releases/${releaseId}/pir/findings/${findingId}/incidents`, data)
      .then((r) => r.data),
  unciteIncident: (releaseId: number, findingId: number, incidentId: number) =>
    api.delete(`/releases/${releaseId}/pir/findings/${findingId}/incidents/${incidentId}`)
      .then((r) => r.data),

  listActions: (params: Record<string, unknown> = {}): Promise<Paged<PirActionRow>> =>
    api.get<PirActionRow[]>('/pir-actions', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
};
```

Add to `frontend/src/services/incidentService.ts`:

```ts
  citeOnPir: (
    incidentId: number,
    data: {
      release_id: number;
      finding_id?: number;
      new_finding?: {
        title: string; detail?: string | null; root_cause?: string | null;
        actions?: { title: string; owner_id?: number | null; due_date?: string | null }[];
      };
      note?: string | null;
    },
  ) => api.post<IncidentPirCitation[]>(`/incidents/${incidentId}/pir-citation`, data)
        .then((r) => r.data),
```

Import `IncidentPirCitation` at the top of that file.

- [ ] **Step 5: Run the service test and watch it pass**

Run: `cd frontend && npm run test -- src/services/__tests__/pirService.test.ts`
Expected: 5 passed.

- [ ] **Step 6: See what the type change broke**

Run: `cd frontend && npx tsc --noEmit`
Expected: errors in `ReleasePirTab.tsx` and `IncidentDetail.tsx` referencing the removed fields. **Leave them for Tasks 10 and 11** — do not paper over them with `any` or optional chaining. Note the list of errors; it is the checklist for the next two tasks.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/types/pir.ts frontend/src/types/incident.ts \
        frontend/src/services/pirService.ts frontend/src/services/incidentService.ts \
        frontend/src/services/__tests__/pirService.test.ts
git commit -m "feat(pir): frontend types and service layer for findings, actions and citations"
```

`tsc` is red at this commit by design — the two consuming pages move in Tasks 10 and 11. If your workflow forbids a red commit, fold Tasks 9, 10 and 11 into one commit at the end of Task 11.

---
### Task 10: The release's PIR tab

**Files:**
- Create: `frontend/src/components/releases/pir/ReleasePirTab.tsx`, `PirFindingCard.tsx`, `PirFindingDialog.tsx`, `PirActionsTable.tsx`, `PirActionDialog.tsx`, `PirIncidentCitations.tsx`
- Delete: `frontend/src/components/releases/ReleasePirTab.tsx` (moved, not edited in place)
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx` (import path only)
- Test: `frontend/src/components/releases/pir/__tests__/releasePirTab.test.tsx`

**Interfaces:**
- Consumes: `pirService`, `PIR`, `PirFinding`, `PirAction`, `PirCitation` (Task 9).
- Produces:
  - `<ReleasePirTab releaseId={number} />` — unchanged prop, so `ReleaseDetail` changes only its import path.
  - `<PirFindingCard finding={PirFinding} releaseId={number} onChanged={() => void} />`
  - `<PirFindingDialog open kind finding|null releaseId onClose onSaved />`
  - `<PirActionsTable actions={PirAction[]} releaseId findingId onChanged />`
  - `<PirActionDialog open action|null releaseId findingId onClose onSaved />`
  - `<PirIncidentCitations citations={PirCitation[]} releaseId findingId onChanged />`

The existing file is 246 lines of five textareas and would roughly triple. Split by responsibility, not by layer: a card, its dialog, its actions table, its action dialog, its citations.

- [ ] **Step 1: Write the failing component tests**

Create `frontend/src/components/releases/pir/__tests__/releasePirTab.test.tsx`. Mock `pirService`, not `api` — the service boundary is what this component owns.

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ReleasePirTab from '../ReleasePirTab';
import { pirService } from '../../../../services/pirService';
import type { PIR } from '../../../../types/pir';

vi.mock('../../../../services/pirService', () => ({
  pirService: {
    getForRelease: vi.fn(), create: vi.fn(), update: vi.fn(),
    createFinding: vi.fn(), updateFinding: vi.fn(), deleteFinding: vi.fn(),
    createAction: vi.fn(), updateAction: vi.fn(), deleteAction: vi.fn(),
    citeIncident: vi.fn(), unciteIncident: vi.fn(),
  },
}));

const mocked = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;

const pir = (overrides: Partial<PIR> = {}): PIR => ({
  id: 1, release_id: 3, summary: 'Went out late', status: 'draft', completed_at: null,
  findings: [
    {
      id: 10, kind: 'went_well', seq: 1, title: 'Canary caught it', detail: null,
      root_cause: null, created_at: '2026-08-01T00:00:00Z', actions: [], incidents: [],
    },
    {
      id: 11, kind: 'went_wrong', seq: 1, title: 'No load test before go-live',
      detail: 'Perf suite is opt-in', root_cause: 'The perf gate is optional',
      created_at: '2026-08-01T00:00:00Z',
      actions: [{
        id: 20, finding_id: 11, seq: 1, title: 'Make the perf gate mandatory', detail: null,
        owner_id: 5, owner_username: 'alice', due_date: '2026-09-30T00:00:00Z', status: 'open',
        closed_at: null, closure_note: null, is_overdue: true,
      }],
      incidents: [{
        incident_id: 41, incident_title: 'Checkout 500s', severity: 'P1', status: 'open',
        note: null,
      }],
    },
  ],
  ...overrides,
});

const renderTab = () =>
  render(<MemoryRouter><ReleasePirTab releaseId={3} /></MemoryRouter>);

beforeEach(() => vi.resetAllMocks());

describe('ReleasePirTab', () => {
  it('renders went-well findings before went-wrong ones', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    await screen.findByText('Canary caught it');
    const headings = screen.getAllByRole('heading');
    const text = headings.map((h) => h.textContent).join('|');
    expect(text.indexOf('What went well')).toBeLessThan(text.indexOf('What went wrong'));
  });

  it('shows a went-wrong finding with its root cause', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    expect(await screen.findByText('The perf gate is optional')).toBeInTheDocument();
  });

  it("names an action's owner rather than its id", async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.queryByText(/#5|user 5/i)).not.toBeInTheDocument();
  });

  it("takes the server's overdue verdict rather than comparing dates itself", async () => {
    // due_date is in the future relative to a 2026-08 clock, but the server said
    // overdue. The page must agree with the server, not with the browser's clock.
    const body = pir();
    body.findings[1].actions[0].due_date = '2099-01-01T00:00:00Z';
    mocked.getForRelease.mockResolvedValue(body);
    renderTab();
    expect(await screen.findByText(/overdue/i)).toBeInTheDocument();
  });

  it('shows a cited incident by name, linking to it', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    const link = await screen.findByRole('link', { name: /Checkout 500s/ });
    expect(link).toHaveAttribute('href', '/incidents/41');
  });

  it('offers to create a PIR when the release has none, and creates it', async () => {
    mocked.getForRelease.mockResolvedValue(null);
    mocked.create.mockResolvedValue(pir({ findings: [] }));
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /create pir/i }));
    await waitFor(() => expect(mocked.create).toHaveBeenCalledWith(3, {}));
  });

  it('re-reads the PIR after a finding is added, rather than patching local state', async () => {
    // Re-render, do not just mount: three bugs on this codebase survived
    // mount-only tests because the second read never happened.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.createFinding.mockResolvedValue({});
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getByRole('button', { name: /add what went wrong/i }));
    await userEvent.type(screen.getByLabelText(/title/i), 'Rollback took 40 minutes');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(mocked.getForRelease).toHaveBeenCalledTimes(2));
  });

  it('shows the server error text, not an HTTP status', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.deleteFinding.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: 'kind cannot be changed' } },
      message: 'Request failed with status code 422',
    });
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getAllByRole('button', { name: /delete finding/i })[0]);
    expect(await screen.findByText(/kind cannot be changed/i)).toBeInTheDocument();
  });
});
```

The last test must reject with an **AxiosError shape**, not a plain `Error` carrying the final text: RTK's `miniSerializeError` copies only `name`/`message`/`stack`/`code`, so a plain-`Error` test passes while the app shows "Request failed with status code 422". Use `formatApiError` from `services/apiError.ts` in the component.

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npm run test -- src/components/releases/pir/__tests__/releasePirTab.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Build `PirIncidentCitations.tsx`**

```tsx
/**
 * The incidents cited as evidence for a finding.
 *
 * Each is a link by NAME to the incident itself: the incident is its own record,
 * raised by the ITIL process or by monitoring, and this review neither owns it
 * nor fixes it. Removing a citation is a correction — it deletes the link and
 * nothing else.
 */
import { Chip, Stack, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { PirCitation } from '../../../types/pir';

interface Props {
  citations: PirCitation[];
  releaseId: number;
  findingId: number;
  onRemove: (incidentId: number) => void;
}

export default function PirIncidentCitations({ citations, onRemove }: Props) {
  if (citations.length === 0) return null;
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap sx={{ mt: 1 }}>
      <Typography variant="body2" color="text.secondary">Evidence</Typography>
      {citations.map((c) => (
        <Chip
          key={c.incident_id}
          size="small"
          component={RouterLink}
          to={`/incidents/${c.incident_id}`}
          clickable
          label={`${c.severity} · ${c.incident_title}`}
          onDelete={() => onRemove(c.incident_id)}
        />
      ))}
    </Stack>
  );
}
```

- [ ] **Step 4: Build `PirActionsTable.tsx` and `PirActionDialog.tsx`**

`PirActionsTable` renders a plain MUI `Table` (not a DataGrid — this is a handful of rows inside a card): columns *Action*, *Owner*, *Due*, *Status*, and a row menu with Edit and Delete. Two rules:

```tsx
// The server's verdict, never re-derived. `is_overdue` came from one clock per
// request; comparing `due_date` here would let a browser with a wrong clock
// manufacture a queue of overdue rows nobody can clear.
{action.is_overdue && <Chip size="small" color="error" label="Overdue" />}
```
```tsx
// The owner's NAME travels with the row. Never `#5`, and never resolved here
// against a separately-fetched, capped user list.
<TableCell>{action.owner_username ?? '—'}</TableCell>
```

`PirActionDialog` is a form with *Title*, *Detail*, *Owner* (an autocomplete over `/tenant/users/lite`, whose own contract is default 1000 / max 5000 precisely because every consumer is a picker), *Due date* (`type="date"`), *Status* and, when the status is `done` or `cancelled`, *Closure note*. On save it calls `createAction` or `updateAction` and then `onSaved()`, which re-reads the whole PIR.

- [ ] **Step 5: Build `PirFindingCard.tsx` and `PirFindingDialog.tsx`**

The card shows the finding's title, detail, and — for a went-wrong finding — its root cause under a *Root cause* label, then `PirActionsTable`, then `PirIncidentCitations`, then an *Add action* button. Its menu offers Edit and Delete.

`PirFindingDialog` takes `kind` when creating (it is fixed, not a form field — a finding's kind is which list it is in) and shows *Title*, *Detail*, and *Root cause* only for `went_wrong`. When editing, `kind` is not sent at all: the backend 422s on a change, and sending the unchanged value would be a change the moment someone edits the dialog.

- [ ] **Step 6: Build `ReleasePirTab.tsx`**

```tsx
/**
 * The release's post-implementation review.
 *
 * A PIR is a summary plus two lists: what went well and should keep happening,
 * and what went wrong. A went-wrong finding carries the root-cause analysis and
 * the process actions that answer it, plus any incidents cited as evidence.
 *
 * THE REVIEW FIXES THE PROCESS, NOT THE INCIDENT. An incident cited here is
 * evidence that a process failed; it is its own record, raised by the ITIL
 * process or by monitoring, and closing it is not this page's business.
 *
 * NOTHING HERE REFUSES ANYTHING. An incomplete review with overdue actions
 * blocks no release transition and no deployment — see
 * backend/tests/test_pir_records_never_refuses.py.
 *
 * Every mutation re-reads the whole PIR rather than patching local state: seq
 * numbers, overdue verdicts and action counts are all computed server-side, and
 * a locally-patched row would disagree with them the moment anything else moved.
 */
```

State: `pir`, `loading`, `error`, plus dialog targets. `load()` calls `pirService.getForRelease` and is the single refresh path passed down as `onChanged`. Layout: summary `TextField` + a Draft/Complete `Switch` at the top, then a *What went well* section and a *What went wrong* section, each a heading, its cards, and an *Add what went well* / *Add what went wrong* button. Empty state when `pir === null`: a short line and a **Create PIR** button calling `pirService.create(releaseId, {})`.

Errors go through `formatApiError` from `services/apiError.ts` into a `<Alert severity="error">`.

- [ ] **Step 7: Move the import in `ReleaseDetail.tsx`**

Change the import to `../../components/releases/pir/ReleasePirTab` and delete the old `frontend/src/components/releases/ReleasePirTab.tsx`. The prop is unchanged, so nothing else in that file moves.

Check `ReleaseDetail.tsx`'s `<Tabs>` still carries `variant="scrollable" scrollButtons="auto"` — C4 added the eleventh tab and the strip overflowed off-screen at an ordinary viewport, reachable only by a synthetic automation click. If it is missing, add it back.

- [ ] **Step 8: Run the tests and watch them pass**

Run: `cd frontend && npm run test -- src/components/releases/pir`
Expected: 8 passed.

- [ ] **Step 9: Typecheck, lint, and run the whole frontend suite**

Run:
```bash
cd frontend
npx tsc --noEmit
npm run lint
npm run test
npm run build
```
Expected: all green, except `IncidentDetail.tsx`, which Task 11 fixes. If `npm run test` surfaces a failure in an unrelated file, check whether a new page-level fetch has stolen another test's `mockResolvedValueOnce` on the shared `api` mock — that has happened here before.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/components/releases/pir frontend/src/pages/releases/ReleaseDetail.tsx
git rm frontend/src/components/releases/ReleasePirTab.tsx
git commit -m "feat(pir): release PIR tab as findings, actions and cited evidence"
```

---
### Task 11: The incident panel and the citation dialog

**Files:**
- Create: `frontend/src/components/incidents/LinkIncidentToPirDialog.tsx`
- Modify: `frontend/src/pages/incidents/IncidentDetail.tsx:39,48,88-98,341-425`, `frontend/src/pages/incidents/IncidentList.tsx:136-139`
- Test: `frontend/src/pages/incidents/__tests__/incidentPirCitations.test.tsx`

**Interfaces:**
- Consumes: `incidentService.citeOnPir`, `pirService.getForRelease`, `releaseService.list`, `IncidentPirCitation` (Task 9).
- Produces: `<LinkIncidentToPirDialog open incidentId defaultReleaseId onClose onLinked />`.

This is the task the whole feature exists for. What must be **gone** when it is done: the *Create PIR* button, its `disabled={!detail.fix_release_id}` guard, and the caption *"Link a fix release to create a PIR."*

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/incidents/__tests__/incidentPirCitations.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LinkIncidentToPirDialog from '../../../components/incidents/LinkIncidentToPirDialog';
import { incidentService } from '../../../services/incidentService';
import { pirService } from '../../../services/pirService';
import { releaseService } from '../../../services/releaseService';

vi.mock('../../../services/incidentService', () => ({
  incidentService: { citeOnPir: vi.fn() },
}));
vi.mock('../../../services/pirService', () => ({
  pirService: { getForRelease: vi.fn() },
}));
vi.mock('../../../services/releaseService', () => ({
  releaseService: { list: vi.fn() },
}));

const releases = releaseService as unknown as Record<string, ReturnType<typeof vi.fn>>;
const pirs = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;
const incidents = incidentService as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.resetAllMocks();
  releases.list.mockResolvedValue({
    rows: [{ id: 7, name: 'Release 24.3' }, { id: 8, name: 'Release 24.2' }], total: 2,
  });
  pirs.getForRelease.mockResolvedValue(null);
});

const open = (props = {}) => render(
  <LinkIncidentToPirDialog open incidentId={41} defaultReleaseId={7}
                           onClose={() => {}} onLinked={() => {}} {...props} />,
);

describe('LinkIncidentToPirDialog', () => {
  it('asks the server for releases that have gone live', async () => {
    open();
    await waitFor(() => expect(releases.list).toHaveBeenCalledWith(
      expect.objectContaining({ implemented: true })));
  });

  it('never offers to create a release, and never mentions a fix release', async () => {
    open();
    await screen.findByLabelText(/release/i);
    expect(screen.queryByText(/create.*release/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/fix release/i)).not.toBeInTheDocument();
  });

  it('preselects the causal release when it is one of the live ones', async () => {
    open();
    expect(await screen.findByDisplayValue('Release 24.3')).toBeInTheDocument();
  });

  it('preselects nothing when the causal release has not gone live', async () => {
    releases.list.mockResolvedValue({ rows: [{ id: 8, name: 'Release 24.2' }], total: 1 });
    open({ defaultReleaseId: 7 });
    await screen.findByLabelText(/release/i);
    expect(screen.queryByDisplayValue('Release 24.3')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Release 24.2')).not.toBeInTheDocument();
  });

  it('creates a PIR, a finding and an action in one call when the release has none',
     async () => {
    incidents.citeOnPir.mockResolvedValue([]);
    open();
    await screen.findByDisplayValue('Release 24.3');
    await userEvent.type(screen.getByLabelText(/what went wrong/i), 'No load test');
    await userEvent.type(screen.getByLabelText(/root cause/i), 'Gate optional');
    await userEvent.type(screen.getByLabelText(/first action/i), 'Make the gate mandatory');
    await userEvent.click(screen.getByRole('button', { name: /link/i }));
    await waitFor(() => expect(incidents.citeOnPir).toHaveBeenCalledWith(41, {
      release_id: 7,
      new_finding: {
        title: 'No load test', detail: null, root_cause: 'Gate optional',
        actions: [{ title: 'Make the gate mandatory' }],
      },
      note: null,
    }));
  });

  it('does not warn that the release has no PIR — one is created as part of linking',
     async () => {
    open();
    await screen.findByDisplayValue('Release 24.3');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('offers that release\'s went-wrong findings when it already has a PIR', async () => {
    pirs.getForRelease.mockResolvedValue({
      id: 1, release_id: 7, summary: null, status: 'draft', completed_at: null,
      findings: [
        { id: 10, kind: 'went_well', seq: 1, title: 'Canary caught it', detail: null,
          root_cause: null, created_at: '', actions: [], incidents: [] },
        { id: 11, kind: 'went_wrong', seq: 1, title: 'No load test', detail: null,
          root_cause: null, created_at: '', actions: [], incidents: [] },
      ],
    });
    incidents.citeOnPir.mockResolvedValue([]);
    open();
    await userEvent.click(await screen.findByRole('radio', { name: /existing finding/i }));
    const select = screen.getByLabelText(/finding/i);
    await userEvent.click(select);
    // Only the went-wrong finding: an incident is evidence something went WRONG.
    expect(await screen.findByRole('option', { name: /No load test/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Canary caught it/ })).not.toBeInTheDocument();
  });

  it('shows the server error text, not an HTTP status', async () => {
    incidents.citeOnPir.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: 'supply exactly one of finding_id or new_finding' } },
      message: 'Request failed with status code 422',
    });
    open();
    await screen.findByDisplayValue('Release 24.3');
    await userEvent.type(screen.getByLabelText(/what went wrong/i), 'T');
    await userEvent.click(screen.getByRole('button', { name: /link/i }));
    expect(await screen.findByText(/supply exactly one/i)).toBeInTheDocument();
  });
});
```

Add a second `describe` in the same file for the panel itself, rendering `IncidentDetail` with a mocked `incidentService.get`:

```tsx
describe('IncidentDetail — the PIR panel', () => {
  it('lists citations by release and finding name', async () => { /* asserts
     'Release 24.3' and 'No load test' are rendered, and that the release link
     points at /releases/7 */ });

  it('shows how many process actions are still open', async () => { /* asserts
     '1 of 2 actions open' or equivalent copy is rendered */ });

  it('offers Link to a PIR with no fix release, and never disables it', async () => {
    // The whole point: fix_release_id is null and the control is still live.
    // Also asserts the old copy is gone.
  });

  it('says plainly that no review cites this incident yet, without calling it a gap',
     async () => { /* an uncited incident is an ordinary state, not something to
     close */ });
});
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npm run test -- src/pages/incidents/__tests__/incidentPirCitations.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Build the dialog**

Create `frontend/src/components/incidents/LinkIncidentToPirDialog.tsx`:

```tsx
/**
 * Cite this incident as evidence on a release's post-implementation review.
 *
 * The incident is its own record — raised by the ITIL incident process or by a
 * monitoring tool — and it already links to the release that caused it and the
 * release that will fix it. What this dialog does is different: where an
 * incident is complex, the release manager uses the PIR to fix the PROCESS that
 * let it reach production. The incident is the evidence that the process failed.
 *
 * SO NOTHING HERE PROMPTS CREATING A RELEASE, and nothing asks for a fix
 * release. The old panel disabled its only button until an incident had a
 * fix_release_id and then anchored the review to that fix — backwards twice
 * over.
 *
 * The release picker offers only releases past their implementation date
 * (`?implemented=true`): a release that has not gone live cannot have caused a
 * production incident. That is a HELPER, not a rule — the server accepts any
 * live release, so a release whose actual date nobody recorded is still
 * reviewable through the API.
 *
 * A release with no PIR yet is not an error and shows no warning: the PIR is
 * created as part of the citation, in one call, in one transaction.
 */
```

Fields: a release `Autocomplete` (options from `releaseService.list({ implemented: true, limit: 200 })`, default the `defaultReleaseId` **only if it is in the returned options**); a `RadioGroup` of *Cite an existing finding* / *Create a new finding*, with the existing branch disabled and captioned when `pirService.getForRelease(releaseId)` returns `null` or no `went_wrong` findings; then either a `Select` of that release's `went_wrong` findings, or *What went wrong* / *Root cause* / *First action (optional)* fields; then an optional *Note*.

Submit builds exactly one of `finding_id` / `new_finding` and calls `incidentService.citeOnPir`, then `onLinked()`. Errors through `formatApiError`.

- [ ] **Step 4: Rewrite the panel in `IncidentDetail.tsx`**

Delete `pirCreating`, `handleCreatePir`, and the whole `detail.pir ? ... : ...` block at lines 341–425. Replace with a panel that maps `detail.pir_citations`:

```tsx
{/* ── Post-implementation reviews ─────────────────────────────────── */}
<Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
  <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
    <Typography variant="h6">Post-Implementation Reviews</Typography>
    {/* Never disabled. There is no precondition on citing an incident. */}
    <Button variant="outlined" size="small" onClick={() => setLinkOpen(true)}>
      Link to a PIR
    </Button>
  </Stack>
  <Divider sx={{ mb: 1.5 }} />

  {detail.pir_citations.length === 0 ? (
    <Typography variant="body2" color="text.secondary">
      No review cites this incident yet.
    </Typography>
  ) : (
    <Stack spacing={1.5}>
      {detail.pir_citations.map((c) => (
        <Box key={`${c.pir_id}-${c.finding_id}`}>
          <Typography variant="body2">
            <RouterLink to={`/releases/${c.release_id}`}>{c.release_name}</RouterLink>
            {' — '}{c.finding_title}
          </Typography>
          {c.root_cause && (
            <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>
              {c.root_cause}
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary">
            {c.open_action_count} of {c.action_count} process actions still open
            {c.pir_status === 'complete' ? ' · review complete' : ' · review in draft'}
          </Typography>
        </Box>
      ))}
    </Stack>
  )}
</Paper>

<LinkIncidentToPirDialog
  open={linkOpen}
  incidentId={detail.id}
  defaultReleaseId={detail.release_id}
  onClose={() => setLinkOpen(false)}
  onLinked={() => { setLinkOpen(false); void load(); }}
/>
```

`defaultReleaseId` is `detail.release_id` — the **causal** release, the delivery whose process failed. Never `fix_release_id`.

- [ ] **Step 5: Relabel the incident list column**

In `frontend/src/pages/incidents/IncidentList.tsx:136-139`, change the header from *PIR Status* to *Reviewed*. The field name, the values and the `ComputedColumnHeader` marker all stay — the column is still `pir_status`, still `none`/`draft`/`complete`, still computed after the page is fetched and therefore still unsortable.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `cd frontend && npm run test -- src/pages/incidents`
Expected: all pass, including the pre-existing incident tests. Any that assert on `detail.pir` need updating to `pir_citations` — update them, do not delete them.

- [ ] **Step 7: Prove the old dead end is gone**

Run: `cd frontend && grep -rn "fix release to create\|Create PIR" src/pages/incidents/`
Expected: no matches.

- [ ] **Step 8: Typecheck, lint, whole suite, build**

Run:
```bash
cd frontend
npx tsc --noEmit && npm run lint && npm run test && npm run build
```
Expected: all green. This is the first point in the plan where `tsc` should be clean again.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/incidents/LinkIncidentToPirDialog.tsx \
        frontend/src/pages/incidents
git commit -m "feat(pir): cite an incident on a PIR from the incident page

Removes the Create PIR button, its fix-release precondition and the
'Link a fix release to create a PIR' caption."
```

---
### Task 12: The `/pir-actions` worklist page

**Files:**
- Create: `frontend/src/pages/pir/PirActionList.tsx`
- Create: `frontend/src/pages/pir/__tests__/pirActionList.test.tsx`
- Modify: `frontend/src/App.tsx` (lazy import + route), `frontend/src/components/navConfig.tsx:96-108`

**Interfaces:**
- Consumes: `pirService.listActions`, `PirActionRow` (Task 9), `useServerGrid` with endpoint key `pir-actions` (Task 5 registered it in `sortWhitelists.json`).
- Produces: the route `/pir-actions` and its nav entry under *Release Management*.

Model this page on `frontend/src/pages/contentions/EscalationWorklist.tsx` — same `useServerGrid` shape, same generation-guard against a slow first page overwriting a fast second one.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/pir/__tests__/pirActionList.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import PirActionList from '../PirActionList';
import { pirService } from '../../../services/pirService';
import whitelists from '../../../constants/sortWhitelists.json';

vi.mock('../../../services/pirService', () => ({ pirService: { listActions: vi.fn() } }));
const mocked = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;

const row = (over = {}) => ({
  id: 1, finding_id: 11, finding_title: 'No load test', release_id: 7,
  release_name: 'Release 24.3', pir_status: 'draft', title: 'Make the perf gate mandatory',
  detail: null, owner_id: 5, owner_username: 'alice', due_date: '2026-09-30T00:00:00Z',
  status: 'open', closed_at: null, closure_note: null, is_overdue: true, ...over,
});

beforeEach(() => {
  vi.resetAllMocks();
  mocked.listActions.mockResolvedValue({ rows: [row()], total: 1 });
});

const renderPage = (path = '/pir-actions') =>
  render(<MemoryRouter initialEntries={[path]}><PirActionList /></MemoryRouter>);

describe('PirActionList', () => {
  it('names the release and the finding, never their ids', async () => {
    renderPage();
    expect(await screen.findByText('Release 24.3')).toBeInTheDocument();
    expect(screen.getByText('No load test')).toBeInTheDocument();
    expect(screen.queryByText(/#7|release 7/i)).not.toBeInTheDocument();
  });

  it('names the owner rather than the owner id', async () => {
    renderPage();
    expect(await screen.findByText('alice')).toBeInTheDocument();
  });

  it('sends the status filter to the server, not to a client-side filter', async () => {
    renderPage();
    await screen.findByText('Release 24.3');
    await userEvent.click(screen.getByLabelText(/status/i));
    await userEvent.click(await screen.findByRole('option', { name: /^open$/i }));
    await waitFor(() => expect(mocked.listActions).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: 'open' })));
  });

  it('omits the key entirely for no selection, and never sends the word all', async () => {
    renderPage();
    await screen.findByText('Release 24.3');
    const params = mocked.listActions.mock.calls[0][0];
    expect(params).not.toHaveProperty('status');
    expect(Object.values(params)).not.toContain('all');
  });

  it('reads its filters back off the URL so a shared link reproduces the queue',
     async () => {
    renderPage('/pir-actions?status=open&overdue=true');
    await waitFor(() => expect(mocked.listActions).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'open', overdue: true })));
  });

  it('takes the overdue flag from the server rather than comparing dates', async () => {
    mocked.listActions.mockResolvedValue({
      rows: [row({ due_date: '2099-01-01T00:00:00Z', is_overdue: true })], total: 1,
    });
    renderPage();
    expect(await screen.findByText(/overdue/i)).toBeInTheDocument();
  });

  it('shows the total from the server, not the length of the page', async () => {
    mocked.listActions.mockResolvedValue({ rows: [row()], total: 97 });
    renderPage();
    expect(await screen.findByText(/97/)).toBeInTheDocument();
  });

  it('marks only whitelisted columns sortable', () => {
    // A column left sortable whose field the backend does not whitelist gives the
    // user a header that looks clickable and 422s the moment they click it.
    const sortable = whitelists['pir-actions'].sortable;
    expect(sortable).toEqual(
      expect.arrayContaining(['title', 'status', 'due_date', 'release', 'owner']));
    expect(sortable).not.toContain('finding_title');
    expect(sortable).not.toContain('is_overdue');
  });
});
```

`finding_title` and `is_overdue` must **not** be sortable: the first is a joined column the grid renders but the backend whitelist does not carry, and the second is computed per response — the eighteenth member of docs/pagination.md's permanently-unsortable set.

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npm run test -- src/pages/pir`
Expected: FAIL — module not found.

- [ ] **Step 3: Build the page**

Create `frontend/src/pages/pir/PirActionList.tsx`:

```tsx
/**
 * Every PIR action in the tenant, in one place.
 *
 * A PIR action is a process fix that outlives the release it came from — "make
 * the perf gate mandatory", not "restart the service". Inside the release's own
 * PIR tab it becomes invisible the moment attention moves on, which is the
 * classic reason PIR actions never get done. This page is the point of the
 * feature.
 *
 * READABLE BY ANY TENANT MEMBER, deliberately — the same call the contention and
 * decommission worklists made. Who may EDIT an action is settled on the PIR
 * itself, not by hiding the list.
 *
 * EVERY FILTER RUNS ON THE WIRE. Fetching a page and filtering it in the browser
 * would answer "how many process fixes are overdue" with "however many of the
 * first 25 happen to be", and `.find()` into a capped collection loses the row
 * outright rather than merely hiding it.
 *
 * `is_overdue` IS THE SERVER'S, NEVER RE-DERIVED — computed from one clock per
 * request against the same day boundary the filter uses, so a row cannot be
 * selected as overdue and rendered as not. A browser with a wrong clock cannot
 * manufacture a queue nobody can clear.
 */
```

Columns: *Action* (`title`, sortable), *Release* (`release_name`, sortable as `release`, linking to `/releases/{release_id}`), *Finding* (`finding_title`, `sortable: false`), *Owner* (`owner_username`, sortable as `owner`), *Due* (`due_date`, sortable, with an *Overdue* chip driven by `is_overdue`), *Status* (sortable). Filters: a status `Select`, an owner `Select` (*Anyone* / *Me*, following `EscalationWorklist`'s `ownerParam` shape), and an *Overdue only* checkbox. No-selection values are spelled `any` / `anyone`, never `all`.

Wire with:

```tsx
  const grid = useServerGrid({
    endpoint: 'pir-actions',
    filterKeys: ['status', 'action_owner', 'overdue'],
    onFetch: (params) => { /* generation guard + pirService.listActions */ },
    total,
    totalPending: loading,
  });
```

- [ ] **Step 4: Add the route and the nav entry**

In `frontend/src/App.tsx`, beside the other lazy imports:

```tsx
const PirActionList = lazy(() => import('./pages/pir/PirActionList'));
```
and beside the other routes:
```tsx
<Route path="/pir-actions" element={<PirActionList />} />
```

In `frontend/src/components/navConfig.tsx`, in the *Release Management* children, after *Incidents*:

```tsx
      // Readable by any tenant member, the same call Contention Escalations and
      // Decommissions made: a process fix nobody can see is a process fix nobody
      // does. Who may EDIT an action is settled on the release's PIR tab.
      { label: 'PIR Actions', path: '/pir-actions', icon: <FactCheckIcon /> },
```

Import `FactCheckIcon` from `@mui/icons-material/FactCheck` alongside the other icon imports.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `cd frontend && npm run test -- src/pages/pir`
Expected: 8 passed.

- [ ] **Step 6: Typecheck, lint, whole suite, build**

Run:
```bash
cd frontend
npx tsc --noEmit && npm run lint && npm run test && npm run build
```
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/pir frontend/src/App.tsx frontend/src/components/navConfig.tsx
git commit -m "feat(pir): cross-release PIR action worklist at /pir-actions"
```

---
### Task 13: Docs, the browser pass, and the whole-branch review

**Files:**
- Modify: `docs/pagination.md`, `docs/user-guide.md`, `docs/admin-guide.md`, `docs/phases/phase-5.md`, `docs/phases/phase-9.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: everything. Produces: no code.

The browser pass is not a formality. On C2 and C4 it found defects a fully green suite had missed — a warning printing a raw database id, a tab strip rendering off-screen, a 500 on delete-then-recreate. jsdom cannot render a DataGrid faithfully; the only way to know a grid works is to open it.

- [ ] **Step 1: Run every suite, both engines, and the frontend**

"Both full suites" here means **three**: SQLite, PostgreSQL and the frontend. A regression once survived six verification steps because every one of them ran targeted frontend files.

```bash
cd backend && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
cd ../frontend && npx tsc --noEmit && npm run lint && npm run test && npm run build
```
Expected: green on all three. Paste the counts into the task's notes — "N passed" is the evidence, not the claim.

- [ ] **Step 2: Start the app**

```bash
docker-compose up -d
cd backend && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && npm run dev
```
Log in at http://localhost:5173 as `admin` / `admin123`, tenant `demo`.

- [ ] **Step 3: Walk the journey the feature exists for**

1. Open an incident that has **no fix release**. Confirm the panel reads *Post-Implementation Reviews*, says no review cites it yet, and that **Link to a PIR** is enabled. Confirm the words "fix release" appear nowhere in the panel.
2. Click it. Confirm the release picker offers only releases past their implementation date, and that the incident's causal release is preselected when it qualifies.
3. Choose a release with **no PIR**, create a new finding with a root cause and one action, and link. Confirm no warning about the missing PIR appeared, and that the citation now shows the release name, the finding title and "0 of 1 process actions still open".
4. Follow the release link to that release's **Rollback**-neighbouring *PIR* tab. Confirm the tab is reachable with a real mouse — C4's eleventh tab rendered entirely off-screen at ~1450px and only a synthetic click could reach it.
5. On the PIR tab: confirm the went-wrong finding, its root cause, its action with owner and due date, and the incident chip linking back. Add a went-well finding. Add a second action, give it a due date in the past, and confirm it renders **Overdue**.
6. Open `/pir-actions` from the nav. Confirm both actions are listed by release and finding name, filter to *Overdue only*, and confirm the total in the footer changes with the filter rather than the page.
7. Back on the PIR tab, mark an action **done** and confirm the worklist drops it from the overdue filter.
8. Delete a finding that has a citation on it, and confirm the incident's panel stops listing it.
9. Cite the same incident on a **second** release's PIR and confirm both citations render on the incident.

- [ ] **Step 4: Check the two things a green suite cannot tell you**

- **Delete then re-create.** On one release, delete a finding, then create another with the same title, then delete an action and create another. C4 shipped a whole-table unique constraint that made exactly this sequence a permanent 500. `uq_pir_finding_incident` is on `(finding_id, incident_id)` and citations are hard-deleted, so it should not have that shape — confirm it empirically rather than by reading the DDL.
- **A tenant with no PIRs at all.** Open `/pir-actions` in a tenant that has never held a review. Confirm an empty grid with its own copy, not a spinner and not an error.

- [ ] **Step 5: Record anything the browser pass found**

Fix what is fixable in this task. Anything deferred goes in the docs as a named, described defect — not left in a commit message. C4's rollup-vs-findings divergence and its delete-then-recreate 500 are on record that way and are the reason the next reader knows about them.

- [ ] **Step 6: Update the docs**

- **`docs/pagination.md`** — add `GET /pir-actions` to the bounded set; record `is_overdue` and `finding_title` as permanently unsortable (computed post-query / joined-but-unwhitelisted), continuing the numbered set; record that `GET /releases/{id}/pir`'s nested `findings`/`actions`/`incidents` lists are deliberately unwindowed because they are bounded by one entity's own structure, and say so explicitly rather than leaving the exemption implicit.
- **`docs/user-guide.md`** — a *Post-implementation reviews* section: what a finding is, that the review fixes the process rather than the incident, how to cite an incident from the incident page, and that the PIR action worklist is where process fixes are tracked to closure. State plainly that nothing here blocks a release.
- **`docs/admin-guide.md`** — the two migrations, the fact that `pirbackfill` drops five columns after backfilling them, and that a downgrade re-adds the columns without the text.
- **`docs/phases/phase-5.md`** — SP4 (PIR) is superseded by this work; say what changed and link the spec, rather than editing the original claim to look as though it always said this.
- **`docs/phases/phase-9.md`** — C6's line says "Phase 5 SP4 PIR is the retro half". Update it to point at this work, and note that the configurable PIR-complete close gate remains C6's, not built here.
- **`CLAUDE.md`** — a block in the same shape as the C2 and C4 blocks: what this established and what will bite if forgotten. At minimum: *this work refuses nothing, guarded by a named test*; *the PIR fixes the process, not the incident*; *`kind` is immutable*; *citations are hard-deleted and idempotent on the pair*; *an incident cites a went-wrong finding only*; *`?implemented=true` is a picker filter, not a rule about what may be reviewed*; *`is_overdue` is the server's, computed through `expiry_boundary`*; *the five free-text columns and `PIR.incident_id` are gone, with the backfill rules*; and anything the browser pass found.

- [ ] **Step 7: Request a whole-branch review**

Use the `superpowers:requesting-code-review` skill against the full diff, `main..HEAD`. On C2 and C4 the whole-branch review is one of the two gates that actually caught things — the per-task reviews see a task's diff, not the seams between tasks. Ask it specifically to check: that no rule the code explains at length is unguarded by a named test; that every new `tenant_id` filter fails a test when removed; and that nothing in the diff refuses anything.

- [ ] **Step 8: Commit and finish the branch**

```bash
git add docs CLAUDE.md
git commit -m "docs(pir): findings, actions and incident citations"
```

Then use the `superpowers:finishing-a-development-branch` skill to decide how this integrates.

---

## Self-Review

**Spec coverage.** §3.1 `pir_finding` → Task 1. §3.2 `pir_action` → Tasks 1, 3. §3.3 `pir_finding_incident` → Tasks 1, 4. §3.4 changes to `pir` → Task 6. §4 service rules (composite delegates, `get_for_incident` retired, `pir_status_for_incidents` derived, overdue through `expiry_boundary`) → Tasks 4, 6, 7 and Task 3 respectively. §5.1 release-side routes → Tasks 2, 3, 4. §5.2 worklist → Task 5. §5.3 composite endpoint → Task 7. §5.4 the two changed response shapes → Task 6. §6.1 PIR tab → Task 10. §6.2 incident panel and dialog → Task 11. §6.3 worklist page → Task 12. §7 migration and backfill → Tasks 1 and 6. §8 testing → every task, with the named guard as Task 8 and the browser pass as Task 13. §9 permissions unchanged → no task adds a role gate, which Task 13's review checks.

**Placeholders.** One deliberate ellipsis remains, in Task 7 Step 1, where the release-creation helper must follow whatever `test_releases_api.py` already uses; the step says so explicitly rather than inventing a helper that may not exist. Tasks 10, 11 and 12 give full code for the load-bearing parts (the citation dialog's contract, the overdue rule, the filter shapes) and describe the ordinary form fields rather than transcribing every `TextField` — a skilled developer following the surrounding components will not go wrong there, and the tests pin the behaviour that matters.

**Type consistency.** `pir_finding_service` is the module name throughout, never `pir_findings_service`. `PIR_ACTION_SORTS` matches the `sortWhitelists.json` key `pir-actions` and the `useServerGrid` endpoint key. `is_overdue` is the field name on the model helper, the response schemas and the TypeScript types. `citations_for_incident` (incident side) and `citations_for_findings` (PIR side) are distinct on purpose and used consistently. `review_status_for_incidents` replaces `pir_status_for_incidents` at every call site named in Task 6.
