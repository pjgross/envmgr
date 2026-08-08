# Phase 7 A4 — Project-aware contention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When two projects' bookings collide on an environment, say which project outranks the other and why, and let a human be formally asked to decide with a named owner and a deadline — without ever moving a booking.

**Architecture:** Priority is a nullable rank on `Project` (lower wins). The verdict for a conflict pair is **computed on read** from the two requests' projects — nothing is cached, so a rank change or a project reassignment takes effect immediately with nothing to invalidate. The escalation **is** stored, keyed on the unordered booking pair, but its state (open/answered/expired) is computed too, so expiry needs no background job. Everything rides on `conflict_service`'s existing conflict pairs rather than defining "overlap" a second time.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL/SQLite (both engines in CI); React 18 + TypeScript + MUI + Redux Toolkit.

**Spec:** [docs/superpowers/specs/2026-08-08-project-contention-design.md](../specs/2026-08-08-project-contention-design.md)

## Global Constraints

- **A4 ADVISES; IT NEVER ACTS.** No booking is transitioned, rejected, rescheduled or bumped — not on detection, not on a decision, not on expiry. Task 4 adds the named guard test. If it ever fails, A4 has started acting.
- **The verdict is computed, never stored.** No contention table, no cached winner.
- **Escalation state is computed, never stored.** No background job, no scheduler, no `status` column.
- **A ranked project does NOT beat an unranked one.** Both are `unranked` → no winner.
- **`priority_rank`: LOWER WINS.** Rank 1 outranks rank 2. Null means unranked, a real state.
- **Never define "overlap" a second time** — consume `conflict_service.list_conflicts` / `conflicts_with`.
- **Every filter runs in SQL**; list endpoints take `pagination()` and emit `X-Total-Count`.
- Tenant scoping uses `current_user.active_tenant_id`, never `.tenant_id`. Cross-tenant is **404, never 403**.
- Services never call `db.commit()`; use `db.flush()`.
- Migration DDL is hand-written — never `alembic revision --autogenerate`.
- **Do not run `alembic downgrade -1` against the dev database.** Use a scratch database.
- Soft deletes (`deleted_at`), not hard deletes. All enum-ish columns are `String`, never native enums.
- Entities render **by name**, never `#N`.
- TypeScript strict mode; API calls in the service layer; components call `formatApiError` in their own catch.
- Backend both engines. PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`

## File Structure

| File | Responsibility |
| --- | --- |
| `backend/app/db/models/project.py` | **modify** — add `priority_rank` |
| `backend/app/db/models/contention_escalation.py` | **create** — the one stored table |
| `backend/app/db/migrations/versions/*_contention.py` | **create** — both schema changes, one revision |
| `backend/app/services/contention_service.py` | **create** — the verdict (computed) AND the escalation (stored), mirroring how `agreement_gap_service` holds both the gap predicate and its ack |
| `backend/app/api/v1/schemas/contention.py` | **create** — `ContentionRead`, `EscalationRead`, `EscalationCreate`, `EscalationDecision` |
| `backend/app/api/v1/contentions.py` | **create** — two routers: the escalate POST under `/bookings`, and the worklist + decision under `/contention-escalations` |
| `backend/app/api/v1/conflicts.py` | **modify** — `ConflictItem` gains `contention` |
| `backend/app/api/v1/schemas/conflict.py` | **modify** — the field |
| `backend/app/api/v1/schemas/project.py`, `projects.py`, `services/project_service.py` | **modify** — `priority_rank` on read + update |
| `backend/app/main.py` | **modify** — register the two routers |
| `frontend/src/types/contention.ts` | **create** |
| `frontend/src/services/contentionService.ts` | **create** |
| `frontend/src/components/bookings/ContentionVerdict.tsx` | **create** — one conflict's verdict line + Escalate control |
| `frontend/src/pages/contentions/EscalationWorklist.tsx` | **create** |

`contention_service.py` holds both halves deliberately: they are one subject, and `agreement_gap_service` set that precedent. If it passes ~700 lines, split the escalation half out — but not before.

---

### Task 1: `priority_rank` on Project

**Files:**
- Modify: `backend/app/db/models/project.py`, `backend/app/api/v1/schemas/project.py`, `backend/app/services/project_service.py`, `backend/app/api/v1/projects.py`
- Create: `backend/app/db/migrations/versions/20260809_1000_contention_add_priority_rank_and_escalation.py`
- Test: `backend/tests/integration/test_project_priority_rank.py`

**Interfaces:**
- Produces: `Project.priority_rank: int | None`; `ProjectResponse.priority_rank`; `ProjectUpdate.priority_rank`.

Note the migration created here also adds Task 3's table — one revision for the sub-project, written in full now so there is only one head to reason about.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_project_priority_rank.py`:

```python
"""`project.priority_rank` — LOWER WINS, and null means unranked.

Null is a real state, not a missing value: no project has a rank on first
deploy, and there is no backfill. A4's verdict treats unranked as
"priority does not separate these", never as "loses".
"""
import pytest
from httpx import AsyncClient

from tests.factories import ensure_project


@pytest.mark.asyncio
async def test_a_new_project_is_unranked(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/v1/projects", json={"name": "Unranked By Default"}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["priority_rank"] is None


@pytest.mark.asyncio
async def test_a_rank_can_be_set_and_read_back(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Ranked")

    patched = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 1}, headers=auth_headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["priority_rank"] == 1

    read = await client.get(f"/api/v1/projects/{project.id}", headers=auth_headers)
    assert read.json()["priority_rank"] == 1


@pytest.mark.asyncio
async def test_a_rank_can_be_cleared_back_to_unranked(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    """An explicit null clears it. `update_project` keys on model_fields_set,
    so an OMITTED key means "leave alone" — the contract B1 gave expires_at."""
    project = await ensure_project(db_session, test_tenant.id, name="Clearable")
    await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 3}, headers=auth_headers
    )

    cleared = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": None}, headers=auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["priority_rank"] is None


@pytest.mark.asyncio
async def test_omitting_the_rank_leaves_it_alone(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    project = await ensure_project(db_session, test_tenant.id, name="Untouched")
    await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 2}, headers=auth_headers
    )

    renamed = await client.patch(
        f"/api/v1/projects/{project.id}", json={"name": "Untouched Renamed"},
        headers=auth_headers,
    )
    assert renamed.json()["priority_rank"] == 2


@pytest.mark.asyncio
async def test_a_rank_below_one_is_refused(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant
):
    """Rank 1 is the highest. Zero and negatives are not "even higher" — they
    are a caller who has guessed the direction, and guessing wrong silently is
    the whole reason this field is validated."""
    project = await ensure_project(db_session, test_tenant.id, name="Bad Rank")
    resp = await client.patch(
        f"/api/v1/projects/{project.id}", json={"priority_rank": 0}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_another_tenants_project_rank_is_404_not_403(
    client: AsyncClient, auth_headers: dict, db_session, second_tenant_factory
):
    other_tenant, _ = await second_tenant_factory()
    theirs = await ensure_project(db_session, other_tenant.id, name="Theirs")

    resp = await client.patch(
        f"/api/v1/projects/{theirs.id}", json={"priority_rank": 1}, headers=auth_headers
    )
    assert resp.status_code == 404, resp.text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_project_priority_rank.py -q -p no:logging`
Expected: FAIL — `KeyError: 'priority_rank'` / 422 on the PATCH, because the field does not exist.

- [ ] **Step 3: Add the column to the model**

In `backend/app/db/models/project.py`, inside `class Project`, after `code`:

```python
    # A4's contention priority. LOWER WINS: rank 1 outranks rank 2.
    #
    # NULL MEANS UNRANKED, and that is a real state rather than a missing
    # value — no project has a rank on first deploy and there is no backfill.
    # A4's verdict reports an unranked pair as "priority does not separate
    # these", never as a loss: treating unranked as lowest would declare the
    # entire existing estate the loser the day this ships, which is the shape
    # B1's governance-gap chip took when it flagged every environment.
    priority_rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
```

Add `Integer` to the `sqlalchemy` import on line 18.

- [ ] **Step 4: Write the migration**

Confirm `cd backend && uv run alembic current` prints `relidx`. Create
`backend/app/db/migrations/versions/20260809_1000_contention_add_priority_rank_and_escalation.py`:

```python
"""A4: project priority rank, and the contention escalation record

Revision ID: contention
Revises: relidx
Create Date: 2026-08-09

Two schema changes, one revision, because they are one sub-project and a single
head is easier to reason about than two.

`project.priority_rank` is nullable with NO BACKFILL, deliberately: unranked is
a real state and A4 reports an unranked pair as "priority does not separate
these" rather than picking a winner.

`contention_escalation` stores only the ASKING and the ANSWER. The verdict is
computed on read, and the escalation's own state (open/answered/expired) is
computed from `respond_by` and `decided_at` — there is no status column and
nothing to run on a schedule.
"""
import sqlalchemy as sa
from alembic import op

revision = "contention"
down_revision = "relidx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("project", sa.Column("priority_rank", sa.Integer(), nullable=True))

    op.create_table(
        "contention_escalation",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenant.id"), nullable=False),
        # NORMALISED: booking_id < other_booking_id. A conflict is symmetric, so
        # (A,B) and (B,A) are one contention; without normalisation both owners
        # escalating the same clash create two records, two owners and two clocks.
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=False),
        sa.Column("other_booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=False),
        sa.Column("escalated_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False),
        # Required: an escalation with no deadline can never expire, which would
        # remove the half of §2.12 that makes escalation time-bound.
        sa.Column("respond_by", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision_yields_booking_id", sa.Integer(), sa.ForeignKey("booking.id"), nullable=True
        ),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # `booking.id` is globally unique, so the pair alone is correct without
        # tenant_id — and leaving it out is what makes a second row impossible
        # rather than merely unlikely.
        sa.UniqueConstraint("booking_id", "other_booking_id", name="uq_contention_pair"),
    )
    op.create_index("ix_contention_escalation_id", "contention_escalation", ["id"])
    op.create_index("ix_contention_escalation_tenant_id", "contention_escalation", ["tenant_id"])
    op.create_index("ix_contention_escalation_booking_id", "contention_escalation", ["booking_id"])
    op.create_index(
        "ix_contention_escalation_other_booking_id", "contention_escalation", ["other_booking_id"]
    )
    op.create_index(
        "ix_contention_escalation_owner_user_id", "contention_escalation", ["owner_user_id"]
    )


def downgrade() -> None:
    op.drop_table("contention_escalation")
    op.drop_column("project", "priority_rank")
```

`ix_contention_escalation_id` is included on purpose: `Base` declares `id` with `index=True`, and omitting it is exactly the divergence issue #5 had to migrate in afterwards.

- [ ] **Step 5: Apply it and verify by hand**

```bash
cd backend && uv run alembic upgrade head
```

**`tests/test_migration_schema_drift.py` compares column NAME SETS only** — not types, nullability, defaults or indexes. Verify by building two scratch PostgreSQL databases (one `alembic upgrade head`, one `create_all`) and diffing `information_schema.columns` and `pg_indexes.indexdef` for `project` and `contention_escalation`. That recipe is the only real evidence; it is what caught four drifts on B3a.

If applying to dev raises `DuplicateTableError`, the running backend's `init_db()`/`create_all` built it first — drop the stray object and re-run. Do **not** stamp.

- [ ] **Step 6: Add the field to the schemas and service**

In `backend/app/api/v1/schemas/project.py`, add to `ProjectResponse`:

```python
    # A4's contention priority. LOWER WINS; null means unranked.
    priority_rank: Optional[int] = None
```

and to `ProjectUpdate`:

```python
    # `int | None`, not Optional-with-default-omitted: the service keys on
    # model_fields_set, so an omitted key means "leave alone" and only an
    # explicit null clears the rank — the contract B1 gave expires_at.
    # ge=1 because rank 1 is the HIGHEST: 0 and negatives are a caller who
    # guessed the direction, and a silent wrong guess is what this refuses.
    priority_rank: Optional[int] = Field(None, ge=1)
```

Add `Field` to the `pydantic` import. Add `priority_rank` to `ProjectCreate` the same way if that schema exists; if it does not accept it, the first test creates an unranked project, which is the required behaviour.

`update_project`'s existing blanket `setattr` over `model_fields_set` needs no change.

- [ ] **Step 7: Run the tests, both engines, then commit**

```bash
cd backend && uv run pytest tests/integration/test_project_priority_rank.py tests/integration/test_projects_api.py -q -p no:logging
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/integration/test_project_priority_rank.py -q -p no:logging
git add backend/app/db/models/project.py backend/app/db/migrations/versions/ backend/app/api/v1/schemas/project.py backend/app/api/v1/projects.py backend/app/services/project_service.py backend/tests/integration/test_project_priority_rank.py
git commit -m "feat(contention): a nullable priority rank on Project, lower wins"
```

---

### Task 2: The verdict

**Files:**
- Create: `backend/app/services/contention_service.py`, `backend/tests/test_contention_verdict.py`

**Interfaces:**
- Consumes: `Project.priority_rank` (Task 1); `conflict_service.conflicts_with`.
- Produces:
  - `ContentionVerdict` — `NamedTuple(outcome: str, winner_booking_id: Optional[int], reason: str)`
  - `OUTCOME_RANKED = "ranked"`, `OUTCOME_NO_PROJECT = "no_project"`, `OUTCOME_UNRANKED = "unranked"`, `OUTCOME_EQUAL_RANK = "equal_rank"`
  - `async def verdicts_for_pairs(db, pairs: Iterable[tuple[int, int]], tenant_id: int) -> dict[tuple[int, int], ContentionVerdict]`
  - `async def verdict_for_pair(db, booking_id: int, other_booking_id: int, tenant_id: int) -> ContentionVerdict`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_contention_verdict.py`. Cover, each as its own named test:

- **both projects ranked, ranks differ → `ranked`**, and `winner_booking_id` is the LOWER rank's booking;
- **either booking's request names no project → `no_project`**, no winner — including the case where the OTHER one is ranked, which pins that a ranked project does not beat an unranked one;
- **both have projects, one has no rank → `unranked`**, no winner;
- **both ranked, same rank → `equal_rank`**, no winner;
- **two bookings of the SAME project → `equal_rank`** (same rank by construction);
- **every no-winner outcome carries a non-empty `reason` naming why**, and the three reasons differ from each other;
- **another tenant's project rank never decides our verdict** — seed a booking whose request points at a project in another tenant and assert the outcome is not `ranked`;
- **`verdicts_for_pairs` answers only about the pairs it was given**;
- **an empty pair list asks the database nothing** (returns `{}`);
- **the batch and the single form agree** over one mixed population containing all four outcomes — asserted **against each other**, not separately. A1 shipped a count and a list, written three tasks apart, that disagreed two ways.

Use `tests/factories.py` (`ensure_project`, `ensure_environment`, `make_booking`) — never fabricate a foreign key. `make_booking` takes `project_id`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_contention_verdict.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.contention_service'`

- [ ] **Step 3: Write the verdict**

Create `backend/app/services/contention_service.py`:

```python
"""Which project outranks the other, and — far more often — why neither does.

A4 ADVISES; IT NEVER ACTS. Nothing here transitions, rejects or reschedules a
booking. `test_a_contention_changes_no_booking_behaviour` is the guard on that
promise; if it fails, A4 has started acting.

THE VERDICT IS COMPUTED, NEVER STORED. It depends on two bookings AND two
project ranks, so four separate edits could falsify a cached one — a worse
invalidation surface than A3's gap, which is computed for the same reason.
Changing a rank or setting a project on a project-less request therefore takes
effect immediately, with nothing to invalidate.

THREE OF THE FOUR OUTCOMES ARE "NO WINNER", each reported with its reason
rather than a fabricated ordering. On today's data almost every pair is
`no_project` — A1 shipped `project_id` nullable with no backfill — so the
honest answer is exactly what makes the unranked estate visible instead of
hiding it behind a spurious winner. Same rule as the drift report's absence
categories, which return null with a reason and never `[]`.
"""
from typing import Iterable, NamedTuple, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.project import Project

OUTCOME_RANKED = "ranked"
OUTCOME_NO_PROJECT = "no_project"
OUTCOME_UNRANKED = "unranked"
OUTCOME_EQUAL_RANK = "equal_rank"


class ContentionVerdict(NamedTuple):
    outcome: str
    winner_booking_id: Optional[int]
    reason: str


async def _ranks_for(
    db: AsyncSession, booking_ids: set[int], tenant_id: int
) -> dict[int, tuple[Optional[int], Optional[int]]]:
    """booking id -> (project_id, priority_rank), for live bookings in this tenant.

    The Project join is LEFT and tenant-filtered on BOTH sides: a booking whose
    request points at another tenant's project must read as project-less here,
    not as ranked. `Project.deleted_at` is filtered because an archived project
    should not win an argument — unlike `get_project_names`, which deliberately
    does not filter it, because rendering an archived name and letting it decide
    a contention are different questions.
    """
    rows = (await db.execute(
        select(Booking.id, BookingRequest.project_id, Project.priority_rank)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id)
        .join(
            Project,
            (Project.id == BookingRequest.project_id)
            & (Project.tenant_id == tenant_id)
            & (Project.deleted_at.is_(None)),
            isouter=True,
        )
        .where(Booking.id.in_(booking_ids), Booking.tenant_id == tenant_id)
    )).all()
    return {bid: (pid, rank) for bid, pid, rank in rows}


def _decide(
    a_id: int, a: tuple[Optional[int], Optional[int]],
    b_id: int, b: tuple[Optional[int], Optional[int]],
) -> ContentionVerdict:
    a_project, a_rank = a
    b_project, b_rank = b
    if a_project is None or b_project is None:
        return ContentionVerdict(
            OUTCOME_NO_PROJECT, None,
            "at least one booking is not linked to a project",
        )
    if a_rank is None or b_rank is None:
        # A RANKED PROJECT DOES NOT BEAT AN UNRANKED ONE. See the module note.
        return ContentionVerdict(
            OUTCOME_UNRANKED, None,
            "at least one project has no priority rank",
        )
    if a_rank == b_rank:
        return ContentionVerdict(
            OUTCOME_EQUAL_RANK, None,
            "both projects have the same priority rank",
        )
    winner = a_id if a_rank < b_rank else b_id  # LOWER WINS
    return ContentionVerdict(OUTCOME_RANKED, winner, "the higher-priority project wins")


async def verdicts_for_pairs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]], tenant_id: int
) -> dict[tuple[int, int], ContentionVerdict]:
    """One query for a page of conflict pairs. Keyed by the pair AS GIVEN."""
    pairs = list(pairs)
    if not pairs:
        return {}
    ids = {b for pair in pairs for b in pair}
    ranks = await _ranks_for(db, ids, tenant_id)
    missing = (None, None)
    return {
        (a, b): _decide(a, ranks.get(a, missing), b, ranks.get(b, missing))
        for a, b in pairs
    }


async def verdict_for_pair(
    db: AsyncSession, booking_id: int, other_booking_id: int, tenant_id: int
) -> ContentionVerdict:
    """The single-pair form. DERIVED FROM THE BATCH, not a second implementation
    — two mechanisms answering one question means one test cannot guard both."""
    return (await verdicts_for_pairs(db, [(booking_id, other_booking_id)], tenant_id))[
        (booking_id, other_booking_id)
    ]
```

- [ ] **Step 4: Run the tests, then mutate**

Run the file on SQLite, then PostgreSQL. Then, for EACH of these, remove the rule and confirm a **named** test fails, restoring after each:

- `Project.tenant_id == tenant_id` in the join
- `Project.deleted_at.is_(None)` in the join
- `Booking.tenant_id == tenant_id` in the where
- `Booking.id.in_(booking_ids)` in the where
- `a_rank < b_rank` → `>` (proves LOWER WINS is tested, not assumed)
- the `a_rank is None or b_rank is None` branch (proves ranked-does-not-beat-unranked)

A rule no named test protects is not done. Add the missing test before moving on.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/contention_service.py backend/tests/test_contention_verdict.py
git commit -m "feat(contention): the verdict, computed from project ranks"
```

---

### Task 3: The escalation record

**Files:**
- Create: `backend/app/db/models/contention_escalation.py`, `backend/tests/test_contention_escalation.py`
- Modify: `backend/app/db/models/__init__.py`, `backend/app/services/contention_service.py`

**Interfaces:**
- Consumes: `app.core.upsert.insert_or_reread(db, row, reread) -> tuple[T, bool]`; `conflict_service.list_conflicts`.
- Produces:
  - `STATE_OPEN = "open"`, `STATE_ANSWERED = "answered"`, `STATE_EXPIRED = "expired"`
  - `def normalise_pair(a: int, b: int) -> tuple[int, int]`
  - `def escalation_state(escalation, now: datetime) -> str`
  - `async def get_escalation(db, booking_id, other_booking_id, tenant_id) -> Optional[ContentionEscalation]`
  - `async def escalations_for_pairs(db, pairs, tenant_id) -> dict[tuple[int, int], ContentionEscalation]`
  - `async def create_escalation(db, *, booking_id, other_booking_id, owner_user_id, respond_by, current_user, tenant_id) -> ContentionEscalation`
  - `async def record_decision(db, escalation_id, *, yields_booking_id, notes, current_user, tenant_id) -> ContentionEscalation`
  - `async def bookings_live(db, escalations, tenant_id) -> dict[int, bool]` — batch: is each escalation's pair still live (neither soft-deleted, neither in a terminal state)? Computed, never stored; an escalation outlives its bookings on purpose.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_contention_escalation.py` covering, each as its own named test:

- **escalating from either direction yields ONE record** — escalate (A,B), then (B,A), and assert one row exists and the second call returns it rather than erroring;
- **the stored pair is normalised** — `booking_id < other_booking_id` regardless of call order;
- **state is `open`** with a future `respond_by` and no decision;
- **state is `expired`** with a past `respond_by` and no decision — **with no job having run**;
- **state is `answered`** once a decision is recorded, **even when `respond_by` has passed** (answering late is still answered, not expired);
- **recording a decision stores which booking yields, the notes, who decided and when**;
- **a decision naming a booking outside the pair is refused** (400);
- **escalating a pair that is not actually in conflict is refused** (400) — non-overlapping bookings;
- **another tenant's escalation is invisible**: `get_escalation` returns None for it and `record_decision` on it raises 404, never 403;
- **a lost create race records one escalation** — stub the pre-read to miss once, exactly as `tests/test_ack_upsert_races.py` does, and assert no `IntegrityError` and one row;
- **`escalations_for_pairs` answers only about the pairs it was given**, and returns `{}` for an empty list.

- [ ] **Step 2: Run it to verify it fails, then write the model**

Create `backend/app/db/models/contention_escalation.py`:

```python
"""A formal request for a human to decide a contention.

ONLY THE ASKING AND THE ANSWER ARE STORED. The verdict is computed by
contention_service, and this record's own STATE is computed too — open,
answered and expired are facts about `respond_by` and `decided_at`, not a
column something has to write. That is why A4 needs no background job.

Keyed on the UNORDERED pair: a conflict is symmetric, so (A,B) and (B,A) are
one contention. Without normalisation plus the unique constraint, both owners
escalating the same clash create two records with two owners and two clocks.

A4 NEVER MOVES A BOOKING. `decision_yields_booking_id` records which booking a
human said should give way; acting on it is the owning team's job, through the
ordinary transition path. That matters for A2 group bookings — the team moves
their whole group atomically, and A4 never reaches inside one.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentionEscalation(Base):
    __tablename__ = "contention_escalation"
    __table_args__ = (
        # `booking.id` is globally unique, so the pair alone is correct without
        # tenant_id — and leaving it out is what makes a second row impossible
        # rather than merely unlikely.
        UniqueConstraint("booking_id", "other_booking_id", name="uq_contention_pair"),
    )

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    # NORMALISED: booking_id < other_booking_id. See normalise_pair.
    booking_id: Mapped[int] = mapped_column(
        ForeignKey("booking.id"), nullable=False, index=True
    )
    other_booking_id: Mapped[int] = mapped_column(
        ForeignKey("booking.id"), nullable=False, index=True
    )
    escalated_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id"), nullable=False, index=True
    )
    # REQUIRED: an escalation with no deadline can never expire, which would
    # remove the half of §2.12 that makes escalation time-bound.
    respond_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_yields_booking_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("booking.id"), nullable=True
    )
    decision_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[int]] = mapped_column(ForeignKey("user.id"), nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

Register it in `backend/app/db/models/__init__.py` beside the other models.

- [ ] **Step 3: Add the escalation half of the service**

Append to `backend/app/services/contention_service.py`. Key points the implementer must honour:

```python
STATE_OPEN = "open"
STATE_ANSWERED = "answered"
STATE_EXPIRED = "expired"


def normalise_pair(a: int, b: int) -> tuple[int, int]:
    """(min, max). A conflict is symmetric; the record is not."""
    return (a, b) if a < b else (b, a)


def escalation_state(escalation, now: datetime) -> str:
    """COMPUTED, never stored — which is why A4 needs no scheduler.

    Answering LATE is still `answered`: the decision arrived, and rewriting it
    as expired would lose the fact that someone did decide.
    """
    if escalation.decided_at is not None:
        return STATE_ANSWERED
    if _utc(escalation.respond_by) < now:
        return STATE_EXPIRED
    return STATE_OPEN
```

`_utc` normalises a naive datetime to UTC — SQLite returns naive values for `DateTime(timezone=True)` while PostgreSQL returns aware ones, and comparing the two raises. Copy the helper from `agreement_gap_service._utc`.

`create_escalation` must:
1. normalise the pair;
2. **verify the two bookings are actually in conflict** via `conflict_service.list_conflicts` — a pair that does not overlap is a 400 naming why. Do not re-derive overlap;
3. verify both bookings are in this tenant (404 otherwise);
4. verify `owner_user_id` is a user in this tenant (404 otherwise);
5. build the row and go through `insert_or_reread(db, row, lambda: get_escalation(...))`, returning the existing record when the race is lost;
6. `db.flush()`, never `db.commit()`.

`record_decision` must:
1. load the escalation tenant-scoped — 404 if absent or another tenant's;
2. refuse a `yields_booking_id` that is neither of the pair (400);
3. set `decision_yields_booking_id`, `decision_notes`, `decided_by`, `decided_at`;
4. **change nothing on either booking.**

- [ ] **Step 4: Run tests, both engines, mutate, then commit**

Mutate and confirm a named test fails for each: the normalisation, the unique constraint, the `decided_at`-before-`respond_by` order in `escalation_state`, each tenant filter, and the pair membership check in `record_decision`.

```bash
git add backend/app/db/models/contention_escalation.py backend/app/db/models/__init__.py backend/app/services/contention_service.py backend/tests/test_contention_escalation.py
git commit -m "feat(contention): the escalation record, with computed state"
```

---

### Task 4: API surface, and the never-acts guard

**Files:**
- Create: `backend/app/api/v1/schemas/contention.py`, `backend/app/api/v1/contentions.py`, `backend/tests/integration/test_contention_api.py`
- Modify: `backend/app/api/v1/schemas/conflict.py`, `backend/app/api/v1/conflicts.py`, `backend/app/main.py`

**Interfaces:**
- Consumes: everything from Tasks 2 and 3.
- Produces: `ContentionRead`, `EscalationRead`, `EscalationCreate`, `EscalationDecision`; `ConflictItem.contention`.

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_contention_api.py` must cover:

- `GET /bookings/{id}/conflicts` returns a `contention` object per item, with `outcome`, `winner_booking_id` and `reason`, **and the outcome matches `verdict_for_pair` for the same pair** — asserted against each other, not against a literal;
- the four outcomes over one mixed population, read through the endpoint;
- `POST /bookings/{id}/contentions/{other_id}/escalate` returns 201 and the record; **called twice, it returns the same record** with 200 the second time;
- escalating a non-conflicting pair is **400**, naming why;
- escalating as a user who is neither owner, delegate nor Admin is **403**;
- escalating another tenant's booking is **404**;
- `PUT /contention-escalations/{id}/decision` as the named owner succeeds;
- as an **Admin who is not the owner** it succeeds — the B3b lesson: gating solely on one person leaves a workflow stuck when they leave;
- as any other user it is **403**;
- on another tenant's escalation it is **404**;
- `GET /contention-escalations` is bounded — assert `X-Total-Count` matches the filtered set, which is the only evidence from outside that the filter ran in SQL;
- filtering by `state=open|answered|expired` returns the right rows, and **omitting the filter returns everything**;
- another tenant's escalations never appear in the list;
- **an escalation whose bookings have moved on keeps its record.** Close or soft-delete one of the pair, then assert the escalation still appears in the worklist and still reads back through the API, flagged `bookings_live: false`. It is the trail of a decision that was asked for, which is the only reason to store it — a record that vanished when a booking closed would erase the audit A4 exists to create. The flag is **computed** from the two bookings' `deleted_at` and terminal status, not stored.

**And the guard the whole sub-project rests on:**

```python
@pytest.mark.asyncio
async def test_a_contention_changes_no_booking_behaviour(
    client: AsyncClient, auth_headers: dict, db_session, test_tenant, test_user,
):
    """A4 ADVISES; IT NEVER ACTS.

    Detecting a contention, escalating it, and recording a decision that names
    a booking must leave both bookings byte-identical — same status, same
    dates, same lifecycle. This is A4's counterpart to A1's
    `test_an_agreement_changes_no_booking_behaviour`, written for the same
    reason: to catch a LATER sub-project quietly making this act. If it fails,
    A4 has started acting.
    """
```

It must snapshot both bookings' `status`, `start_date`, `end_date` and `updated_at` before, run the full escalate-and-decide flow, re-read from the database, and assert every one is unchanged — **including for the booking the decision names as yielding**.

- [ ] **Step 2: Write the schemas**

`backend/app/api/v1/schemas/contention.py` holds `ContentionRead` (`outcome`, `winner_booking_id: Optional[int]`, `reason`, `escalation: Optional[EscalationRead]`), `EscalationRead` (ids, `owner_user_id`, `owner_username: Optional[str]`, `respond_by`, `state`, `bookings_live: bool`, decision fields, `decided_by_username: Optional[str]`), `EscalationCreate` (`owner_user_id: int`, `respond_by: datetime`), `EscalationDecision` (`yields_booking_id: int`, `notes: Optional[str] = None`).

Give every write schema `model_config = ConfigDict(extra="forbid")` so a misspelled key is a 422 rather than a silently dropped field.

**Usernames travel WITH the row**, resolved server-side — the browser must not look them up in the capped tenant-users collection, where a name past the cap is information lost. **Do not tenant-qualify the user join**: under master-admin impersonation an actor can sit outside the record's tenant and would render as nobody. `agreement_gap_service.ack_author_username` carries this rule and the reasoning.

- [ ] **Step 3: Extend the conflicts endpoint**

`ConflictItem` gains `contention: ContentionRead`. **Required, not defaulted** — a defaulted field is what left `has_unacknowledged_conflicts` dead at every construction site since it shipped (issue #4).

In `conflicts.py`'s list handler, resolve verdicts and escalations for the whole page in **two batch calls** (`verdicts_for_pairs`, `escalations_for_pairs`) beside the existing name/gap/conflict batches — never per row. Three sub-projects have now added a field here and every per-row form has had to be undone.

- [ ] **Step 4: Write the routes**

`backend/app/api/v1/contentions.py` with two routers — `router` (prefix `/bookings`) for the escalate POST, and `escalations_router` (prefix `/contention-escalations`) for the worklist GET and the decision PUT. The worklist takes `page: Page = Depends(pagination())` and `sort: Sort = Depends(sorting({...}, default="respond_by"))`, calls `set_total_count`, and applies **state filtering in SQL** (`respond_by`/`decided_at` predicates), never in Python after the page.

Register both in `main.py` under `/api/v1`.

- [ ] **Step 5: Run both engines, mutate, commit**

Mutate: hardcode `contention` to a constant at the conflicts site and confirm a named test fails; drop the state filter's SQL and confirm `X-Total-Count` disagrees; drop the Admin fallback and confirm the named test fails.

```bash
git add backend/app/api/v1/ backend/tests/integration/test_contention_api.py backend/app/main.py
git commit -m "feat(contention): surface the verdict and escalations on the API"
```

---

### Task 5: Frontend types and service

**Files:**
- Create: `frontend/src/types/contention.ts`, `frontend/src/services/contentionService.ts`, `frontend/src/services/__tests__/contentionService.test.ts`
- Modify: `frontend/src/types/conflict.ts`, `frontend/src/types/project.ts`

**Interfaces:**
- Produces: `ContentionOutcome`, `Contention`, `Escalation`, `EscalationState`; `contentionService.escalate(bookingId, otherId, body)`, `.decide(escalationId, body)`, `.list(params)`.

- [ ] **Step 1: Write the failing test, then implement**

Follow `frontend/src/services/agreementGapService.ts` for shape. Assert the **emitted URL, verb and body** — a test that only checks "a function was called" guards nothing, and FastAPI drops unknown query params silently, which has shipped two long-broken filters here.

Wire names are `snake_case`; this codebase does not camelise payloads. Add the new fields as **required** on the response types and give fixtures an explicit value — an optional field would make the type lie about a contract the backend always sends.

`contention` is required on `ConflictItem`; `priority_rank: number | null` is required on the project type.

**No slice thunk** for escalate/decide — they are called from the component, matching `bookingService.transitionState`. That means the component must call `formatApiError` in its own catch; note it where a Task 6 reader will find it.

- [ ] **Step 2: Run, typecheck, commit**

```bash
cd frontend && npx vitest run src/services && npx tsc --noEmit && npx eslint src --max-warnings=0
git add frontend/src/types/ frontend/src/services/
git commit -m "feat(contention): frontend types and service"
```

---

### Task 6: The UI

**Files:**
- Create: `frontend/src/components/bookings/ContentionVerdict.tsx`, `frontend/src/pages/contentions/EscalationWorklist.tsx`, and their tests
- Modify: `frontend/src/pages/bookings/BookingDetail.tsx` (conflicts panel), `frontend/src/pages/admin/ProjectDetail.tsx`, `frontend/src/App.tsx`, `frontend/src/components/navConfig.tsx`

- [ ] **Step 1: Write the failing tests**

- the verdict line renders the server's `reason` for each no-winner outcome, and names the **winning project by name** for `ranked` — never `#N`;
- an Escalate control appears for a live conflict and opens a form with owner and `respond_by`, defaulted **three working days ahead**;
- a failed escalate renders the **server's** message via `formatApiError` — reject with a genuine **AxiosError shape** (`response.data.detail`), never a pre-formatted `Error`, which passes while the app is broken;
- once escalated, the panel shows the owner, the deadline and the state;
- **an expired escalation reads as expired without any refresh** — it is computed server-side;
- the worklist lists escalations with their state and filters by it;
- the project admin page renders the rank field **labelled "1 is highest"**;
- **mount the real `ContentionVerdict` inside a real `BookingDetail`** for at least one test, and prove deleting the wiring fails it by name. On A2, deleting the wiring between a page and its panel left 43 tests green while the feature regressed entirely;
- **re-render at least once** with changed props — switching from a conflict with a verdict to one without must not leave the previous verdict on screen.

- [ ] **Step 2: Implement, run, commit**

Nothing in this UI may disable, gate or hide a booking action. An Escalate control is fine; anything reading as "you cannot proceed" is not.

Where the decision names a booking that belongs to a group, say so — otherwise it reads as "move this one booking", and A2's atomic transition moves the whole group.

```bash
cd frontend && npx vitest run && npx tsc --noEmit && npx eslint src --max-warnings=0
git add frontend/src/
git commit -m "feat(contention): verdict on the conflicts panel, and the escalation worklist"
```

---

### Task 7: Docs, the phase-doc correction, and the browser pass

**Files:**
- Modify: `docs/phases/phase-7.md`, `docs/admin-guide.md`, `docs/user-guide.md`, `docs/pagination.md`, `CLAUDE.md`

- [ ] **Step 1: Correct the phase doc**

Tick A4 and add "What A4 established". **Correct the A4 line itself**: it claims A4 "must decide whether contention resolves per environment or per group". Choosing *rank and advise, never act* dissolves that — an advisory verdict cannot tear a group apart. Say so; do not delete the history.

- [ ] **Step 2: Raise the group-member removal issue**

`DELETE /booking-requests/{id}/environments/{booking_id}` silently shrinks an atomic group booking; nothing refuses it and nothing documents it. It is a pre-existing A2 defect, **out of A4's scope by decision**. Raise it with `gh issue create`, and link it from the phase doc so it stops being an unowned note.

- [ ] **Step 3: The guides and pagination**

Admin guide: what a priority rank is, that **lower wins**, that unranked is normal and means "priority does not separate these", and that **nothing is ever blocked or moved**. User guide: what the verdict line means, and that an escalation asks a person to decide rather than changing the booking. `docs/pagination.md`: add `GET /contention-escalations` and re-run the file's own grep, recording the **delta**, not a re-baseline.

**Verify every claim against the code before writing it.** Four false doc claims shipped on A3 and were caught only at the final review, including one asserting A3's central promise was unguarded when two named tests guarded it.

- [ ] **Step 4: The browser pass** *(the controller runs this)*

Ten defects across the last five sub-projects were found only by opening the page, and jsdom could not render A3's grid column at all.

1. Two bookings, ranked projects, different ranks → the verdict names the winner **by name**.
2. Two bookings, neither project ranked → "priority does not separate these", **no winner invented**.
3. A booking with no project → `no_project`, and the reason says so.
4. Escalate one; confirm the owner, the deadline and `open`.
5. **Set `respond_by` in the past; confirm it reads `expired` with nothing having run.**
6. Record a decision as the owner; confirm it shows, and **confirm both bookings are untouched** — same status and dates.
7. Record a decision as an Admin who is not the owner.
8. Change a project's rank and reload a contention — **the verdict changes with nothing invalidated.**

- [ ] **Step 5: Commit**

```bash
git add docs/ CLAUDE.md
git commit -m "docs: record A4, and correct the phase doc's per-group claim"
```

---

## Final verification

- [ ] **Backend, both engines** — `cd backend && uv run pytest -q -p no:logging`, then the PostgreSQL leg. **One PostgreSQL run at a time**, and never while an implementer or a mutating reviewer is active.
- [ ] **Frontend** — `npx vitest run && npx tsc --noEmit && npx eslint src --max-warnings=0`.
- [ ] **Confirm `test_a_contention_changes_no_booking_behaviour` passes.** If it does not, A4 acts, and the design is violated.
- [ ] **Confirm A1's `test_an_agreement_changes_no_booking_behaviour` still passes** — A4 touches the same response builders A3 did.
- [ ] Final whole-branch review on the most capable model, then `superpowers:finishing-a-development-branch`.
