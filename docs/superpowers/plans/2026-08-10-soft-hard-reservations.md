# Phase 7 B4 — Soft vs Hard Reservations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A booking request declares its claim on an environment **soft** or **hard**, defaulted from its booking type; the level breaks the tie in A4's contention verdict only where project priority cannot separate the pair; and the same booking type carries a default duration so half-day / sprint / release-cycle bookings are one click.

**Architecture:** Three additive columns (two on `booking_type`, one on `booking_request`). The level is inherited at create and changeable only by Admin/Release Manager. A4's `_ranks_for` widens its tuple by one value read from the join it already performs, and `_decide` consults protection **only** in its three existing no-winner branches — so rank stays strictly primary and no verdict rendered today changes. Nothing is refused, nothing is preempted.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Alembic (backend); React 18 + TypeScript + MUI DataGrid + Redux Toolkit (frontend); pytest (dual engine: SQLite + PostgreSQL) and vitest.

**Spec:** [docs/superpowers/specs/2026-08-10-soft-hard-reservations-design.md](../specs/2026-08-10-soft-hard-reservations-design.md) — read it before Task 1. Every "why" below is short because the spec carries it.

## Global Constraints

Every task's requirements implicitly include all of these.

- **B4 ADVISES; IT NEVER BLOCKS AND IT NEVER PREEMPTS.** No booking is refused, transitioned, cancelled or rescheduled by anything in this plan. The only new refusal in the whole sub-project is a **403** when someone without the role *changes* the level. If you find yourself editing `check_overlap`, `validate_transition`, or any lifecycle code, stop — you are outside B4.
- **Rank stays strictly primary.** Protection speaks only in `_decide`'s three existing no-winner branches. A `soft` booking on a better-ranked project still wins.
- **Values are exactly `"soft"` and `"hard"`**, lowercase, from `app/core/protection_levels.py`. Never a bare string literal outside that module and its tests.
- **Enum columns are never native.** `String(20)`, per the house rule (`native_enum=False` everywhere, and `booking.status` is the precedent for a plain `String`).
- **Migrations are hand-written.** `alembic revision -m "..."` then write the DDL yourself. Never `--autogenerate` — `init_db()` calls `create_all`, so autogenerate sees nothing to do.
- **No `db.commit()` in services.** `get_db()` auto-commits; use `db.flush()` when you need an id mid-transaction.
- **Every query on a tenant-scoped table filters `tenant_id`, using `current_user.active_tenant_id`**, never `.tenant_id` — impersonation makes them differ.
- **Never fabricate a foreign key in a test.** Use `backend/tests/factories.py`. SQLite now enforces FKs (`PRAGMA foreign_keys=ON`).
- **Backend test command:** `cd backend && PYTHONPATH=. uv run pytest -q`. Single file: `PYTHONPATH=. uv run pytest tests/path/test_x.py -q`.
- **Frontend test command:** `cd frontend && npx vitest run <path>`.
- **Test cadence (REVISED 2026-08-10, mid-execution, by the owner).** The original rule — both full engine legs at the end of every task — was measured at **15m47s on SQLite and 35m52s on PostgreSQL**, i.e. ~52 minutes per backend task, against 0.6s for the focused tests. That is the development cadence, not the safety margin, so it changed:
  - **Every task:** run the focused test files it touches, plus any suite subset plausibly affected (`-k` or a directory). Fast, foreground.
  - **Full SQLite suite:** at Tasks 5, 7 and 15 only.
  - **Full PostgreSQL suite:** at Tasks 7 and 15 only — plus Task 1, already done, because it carried the migration.
  - CI runs both legs on push regardless, so nothing reaches `main` unverified.
  - The dialect-sensitive work is the migration (Task 1, both legs done), the `?protection=` filter and the sort (Task 5), and the guard (Task 7). Those keep their full runs; the rest do not need them.
- **Full-suite commands, when a task calls for one:** `cd backend && PYTHONPATH=. uv run pytest -q` and `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q`. **Both exceed the 600s foreground Bash limit.** Launch with `run_in_background`, redirect to a fixed log path under the session tasks directory, and wait with an `until grep -qE "[0-9]+ (passed|failed)" <log>; do sleep 20; done` loop. Output sent only to a pipe is lost when the shell ends — a completed 36-minute run was lost exactly that way.
- **Commit per task**, conventional commits (`feat(b4):`, `test(b4):`, `docs(b4):`). Do not push; the branch is merged at the end.
- **Branch:** create `feature/phase7-b4-reservations` off freshly-pulled `main` before Task 1.

---

## File Structure

**Backend — create**
- `backend/app/core/protection_levels.py` — the two constants and the valid set. Its own module, mirroring `app/core/booking_states.py`, so `booking_request_service` and `contention_service` share them without importing each other.
- `backend/app/db/migrations/versions/<rev>_bookingprotection.py` — the three columns.
- `backend/tests/test_b4_advises_never_blocks.py` — the guard on the promise.
- `backend/tests/services/test_protection_verdict.py` — the verdict extension.
- `backend/tests/integration/test_protection_level_api.py` — inheritance, role gate, carve-out, filter, sort.

**Backend — modify**
- `app/db/models/booking_request.py` — `protection_level`
- `app/db/models/booking_lifecycle.py` — `BookingType.default_protection_level`, `.default_duration_minutes`
- `app/api/v1/schemas/booking_request.py` — create/update/response + `EnvBookingSummary`
- `app/api/v1/schemas/booking.py` — `BookingCreate`, `BookingResponse`, `BookingRequestSummary`
- `app/api/v1/schemas/booking_lifecycle.py` — the three `BookingType*` schemas
- `app/services/booking_request_service.py` — inheritance, role gate, `STANDARD_REQUEST_FIELDS`
- `app/services/booking_service.py` — legacy create path inheritance; list filter
- `app/services/contention_service.py` — `_ranks_for`, `_decide`, `OUTCOME_PROTECTED`
- `app/api/v1/bookings.py` — `?protection=`, `BOOKING_SORTS`, response wiring
- `app/api/v1/booking_lifecycle.py` — booking-type defaults

**Frontend — create**
- `frontend/src/constants/protection.ts` — values, labels, the `any` sentinel
- `frontend/src/utils/duration.ts` — `addDuration`, the DST rule
- test files alongside each modified component under `__tests__/`

**Frontend — modify**
- `src/types/bookingRequest.ts`, `src/types/booking.ts`, `src/types/bookingLifecycle.ts`
- `src/constants/sortWhitelists.json` — `bookings.sortable`
- `src/components/admin/BookingTypesPanel.tsx`
- `src/pages/bookings/BookingForm.tsx`, `BookingList.tsx`, `BookingDetail.tsx`, `BookingCalendar.tsx`
- `src/components/bookings/EditStandardFieldsDialog.tsx`, `ContentionVerdict.tsx`
- `src/components/BookingScheduleGantt.tsx`

---

## Task 1: The constants module, the columns, and the migration

**Files:**
- Create: `backend/app/core/protection_levels.py`
- Modify: `backend/app/db/models/booking_request.py`, `backend/app/db/models/booking_lifecycle.py`
- Create: `backend/app/db/migrations/versions/<rev>_bookingprotection.py`
- Test: `backend/tests/integration/test_protection_level_api.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `PROTECTION_SOFT: str = "soft"`, `PROTECTION_HARD: str = "hard"`, `PROTECTION_LEVELS: frozenset[str]`; `BookingRequest.protection_level: str`; `BookingType.default_protection_level: str`; `BookingType.default_duration_minutes: int | None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_protection_level_api.py`:

```python
"""Phase 7 B4 — the protection level end to end.

B4 ADVISES. Nothing here may assert that a booking was refused, moved or
cancelled because of a protection level; `test_b4_advises_never_blocks.py`
holds the guard on that.
"""
import pytest
from sqlalchemy import select

from app.core.protection_levels import (
    PROTECTION_HARD,
    PROTECTION_LEVELS,
    PROTECTION_SOFT,
)
from app.db.models.booking_lifecycle import BookingType
from app.db.models.booking_request import BookingRequest


def test_the_two_levels_are_the_whole_vocabulary():
    assert PROTECTION_LEVELS == {PROTECTION_SOFT, PROTECTION_HARD}
    assert PROTECTION_SOFT == "soft"
    assert PROTECTION_HARD == "hard"


@pytest.mark.asyncio
async def test_a_new_booking_type_defaults_to_soft(db_session, tenant, lifecycle_template):
    bt = BookingType(
        tenant_id=tenant.id,
        name="Ad hoc",
        lifecycle_template_id=lifecycle_template.id,
    )
    db_session.add(bt)
    await db_session.flush()
    await db_session.refresh(bt)
    assert bt.default_protection_level == PROTECTION_SOFT
    # Null means "this type has no preset" — a legitimate state, not a
    # missing value, the same call B1 made for environment.expires_at.
    assert bt.default_duration_minutes is None


@pytest.mark.asyncio
async def test_a_new_request_defaults_to_soft(db_session, tenant, booking_type, user):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    req = BookingRequest(
        tenant_id=tenant.id,
        project_name="Regression",
        booking_type_id=booking_type.id,
        start_date=now,
        end_date=now + timedelta(days=1),
        booked_by=user.id,
    )
    db_session.add(req)
    await db_session.flush()
    await db_session.refresh(req)
    assert req.protection_level == PROTECTION_SOFT

    stored = (await db_session.execute(
        select(BookingRequest.protection_level).where(BookingRequest.id == req.id)
    )).scalar_one()
    assert stored == PROTECTION_SOFT
```

Check `backend/tests/conftest.py` and `backend/tests/factories.py` for the exact fixture names in this repo (`tenant`, `user`, `booking_type`, `lifecycle_template` or their factory equivalents) and use those — do not invent fixtures.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.protection_levels'`

- [ ] **Step 3: Create the constants module**

`backend/app/core/protection_levels.py`:

```python
"""How hard a booking's claim on an environment is.

Its own module, mirroring `app/core/booking_states.py`, because both
`booking_request_service` (which sets the level) and `contention_service`
(which reads it) need these and must not import each other.

SOFT vs HARD is NOT the same axis as `booking_request.exclusive_use_requested`.
Exclusive use asks "can anyone else be in here with me"; this asks "can I be
pushed out". A load test can legitimately need the environment to itself and
still be entirely movable.

B4 ADVISES: nothing in the codebase may refuse, transition or cancel a booking
on the strength of this value. It breaks a tie in `contention_service._decide`
and it is rendered. That is all it does.
"""

PROTECTION_SOFT = "soft"
PROTECTION_HARD = "hard"

PROTECTION_LEVELS = frozenset({PROTECTION_SOFT, PROTECTION_HARD})
```

- [ ] **Step 4: Add the three columns**

In `backend/app/db/models/booking_request.py`, immediately after `exclusive_use_requested` (they belong together and the docstring below explains why they are not the same thing):

```python
    # How hard this claim is — see app/core/protection_levels.py. Values are
    # "soft" | "hard"; String, not a native enum, per the house rule.
    #
    # ON THE REQUEST, NOT THE BOOKING, and that is load-bearing. A2's group
    # bookings share ONE BookingRequest, and A4's argument that "group
    # reachability is exactly equal to individual reachability" depends on
    # `_record_values` being byte-identical across members. A per-booking
    # override would let one member of an atomic group be protected and another
    # not, which the group transition cannot express. Do not add one without
    # revisiting that argument.
    protection_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="soft", default="soft"
    )
```

In `backend/app/db/models/booking_lifecycle.py`, on `BookingType`, after `color`:

```python
    # The protection level a request inherits from this type. A tenant declares
    # once, in the vocabulary it already configures, that (say) release-cycle
    # bookings are protected and ad-hoc ones are not.
    default_protection_level: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="soft", default="soft"
    )
    # The preset duration for this type, in minutes — 240 for a half-day,
    # 20160 for a two-week sprint. NULLABLE, and null means "this type has no
    # preset": a legitimate state, not a missing value.
    #
    # A CONVENIENCE, NEVER A CONSTRAINT. Nothing server-side checks that a
    # booking's length matches it, so a tenant editing a preset does not
    # retroactively make live bookings wrong.
    default_duration_minutes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
```

Add `Integer` to the `sqlalchemy` import line in `booking_lifecycle.py` if it is not already there.

- [ ] **Step 5: Write the migration**

Run `cd backend && uv run alembic revision -m "bookingprotection"`, then replace the generated body:

```python
"""Phase 7 B4 — soft/hard reservations and booking-type duration presets.

ADDITIVE ONLY: three columns, no backfill beyond the server defaults, no data
migration, no index. Every existing row lands on 'soft', which is what makes
this inert — see test_the_migration_is_inert in
tests/services/test_protection_verdict.py.

No index on protection_level: it is a low-cardinality filter always applied
alongside the tenant filter, so one would not be used. Phase 11 may want one
for an estate-wide cost aggregation; that is Phase 11's call, with a query in
front of it.
"""
import sqlalchemy as sa
from alembic import op

revision = "<generated>"
down_revision = "<generated — leave as alembic wrote it>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "booking_type",
        sa.Column(
            "default_protection_level",
            sa.String(20),
            nullable=False,
            server_default="soft",
        ),
    )
    op.add_column(
        "booking_type",
        sa.Column("default_duration_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "booking_request",
        sa.Column(
            "protection_level",
            sa.String(20),
            nullable=False,
            server_default="soft",
        ),
    )


def downgrade() -> None:
    op.drop_column("booking_request", "protection_level")
    op.drop_column("booking_type", "default_duration_minutes")
    op.drop_column("booking_type", "default_protection_level")
```

**Do not run `alembic downgrade -1` against the dev database to test this.** It steps back from whatever the current head is, not from your revision — doing exactly that once dropped `tenant_secret` and wiped the dev tenant's stored GitHub token. Check `alembic current` first and use a scratch database.

- [ ] **Step 6: Apply the migration and run the tests**

Run:
```bash
cd backend && uv run alembic current && uv run alembic upgrade head
PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q
```
Expected: PASS, 3 tests.

- [ ] **Step 7: Verify the migration matches the models by hand**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_migration_schema_drift.py -q`
Expected: PASS — **but that is not evidence.** That test compares only column NAME SETS, not types, defaults or indexes; B3a shipped four real drifts past it. Open the migration and the two model files side by side and confirm the `String(20)`, the `nullable`, and the `server_default` on each of the three columns match. State in the commit message that you did.

- [ ] **Step 8: Run the whole backend suite on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q
```
Expected: PASS on both. A `NOT NULL` column added to a table with existing rows is the classic failure here, and the server default is what prevents it.

- [ ] **Step 9: Commit**

```bash
git add backend/app/core/protection_levels.py backend/app/db/models/booking_request.py \
        backend/app/db/models/booking_lifecycle.py backend/app/db/migrations/versions/ \
        backend/tests/integration/test_protection_level_api.py
git commit -m "feat(b4): protection level column, booking-type defaults, migration"
```

---

## Task 2: Inheritance and the role gate on create

**Files:**
- Modify: `backend/app/services/booking_request_service.py:95-175` (`create_request`), `backend/app/services/booking_service.py:167` (`create_booking`)
- Modify: `backend/app/api/v1/schemas/booking_request.py` (`BookingRequestCreate`), `backend/app/api/v1/schemas/booking.py` (`BookingCreate`)
- Test: `backend/tests/integration/test_protection_level_api.py`

**Interfaces:**
- Consumes: `PROTECTION_SOFT`, `PROTECTION_HARD`, `PROTECTION_LEVELS` from Task 1.
- Produces: `booking_request_service.assert_may_set_protection(current_user: User, *, submitted: str | None, current: str) -> None` — raises `HTTPException(403)`; returns `None` when `submitted` is `None` or equals `current`. Task 3 reuses it verbatim.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/integration/test_protection_level_api.py`:

```python
@pytest.mark.asyncio
async def test_a_request_inherits_its_booking_types_default(
    client, auth_headers, hard_booking_type, environment
):
    """The level is INHERITED, not defaulted to soft, when the type says hard."""
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=auth_headers,
        json={
            "project_name": "Release 24.4",
            "booking_type_id": hard_booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_an_admin_may_override_the_inherited_level(
    client, auth_headers, booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=auth_headers,  # the shared fixture user is an Admin
        json={
            "project_name": "Perf run",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_a_developer_may_not_choose_a_level(
    client, developer_headers, booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=developer_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 403
    assert "protection" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_a_developer_may_send_the_inherited_level_unchanged(
    client, developer_headers, booking_type, environment
):
    """THE CARVE-OUT, AND IT IS LOAD-BEARING, NOT TIDY.

    BookingForm shows a non-admin their inherited level read-only and submits
    the whole form including it. Without this, the primary create journey 403s
    for everyone who is not an Admin or a Release Manager.
    """
    assert booking_type.default_protection_level == PROTECTION_SOFT
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=developer_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": PROTECTION_SOFT,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_SOFT


@pytest.mark.asyncio
async def test_an_unknown_level_is_refused(
    client, auth_headers, booking_type, environment
):
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=auth_headers,
        json={
            "project_name": "Perf run",
            "booking_type_id": booking_type.id,
            "start_date": "2026-09-01T09:00:00Z",
            "end_date": "2026-09-05T17:00:00Z",
            "environment_ids": [environment.id],
            "protection_level": "granite",
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_the_legacy_single_environment_path_inherits_too(
    client, auth_headers, hard_booking_type, environment
):
    """POST /bookings/ builds its own BookingRequest and must not skip this."""
    r = await client.post(
        "/api/v1/bookings/",
        headers=auth_headers,
        json={
            "environment_id": environment.id,
            "project_name": "Legacy path",
            "booking_type_id": hard_booking_type.id,
            "start_date": "2026-10-01T09:00:00Z",
            "end_date": "2026-10-02T17:00:00Z",
        },
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["request"]["protection_level"] == PROTECTION_HARD
```

Add two fixtures to this file (or to `conftest.py` if the repo's convention puts them there): `hard_booking_type` — a `BookingType` with `default_protection_level=PROTECTION_HARD` — and `developer_headers` — auth headers for a user with `role=Role.DEVELOPER` in the same tenant. Build them with `tests/factories.py` helpers; never fabricate ids.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: FAIL — the inherited value comes back `"soft"`, and the 403 tests return 201.

- [ ] **Step 3: Add the schema fields**

`app/api/v1/schemas/booking_request.py`, on `BookingRequestCreate`, after `exclusive_use_requested`:

```python
    # None means "inherit the booking type's default". A caller who is not an
    # Admin or Release Manager may send the inherited value but may not choose
    # a different one — see booking_request_service.assert_may_set_protection.
    protection_level: Optional[Literal["soft", "hard"]] = None
```

Add `Literal` to the `typing` import. Add `model_config = ConfigDict(extra="forbid")` to `BookingRequestCreate` if it does not already have it — that is the A4 `ProjectCreate` silent-drop lesson, and it 422s an *unknown* key, which is a different guard from the role check's 403 on a *known* one.

On `BookingRequestResponse` and on `EnvBookingSummary`, add:

```python
    protection_level: str
```

Required, not defaulted, for the reason `EnvBookingSummary.agreement_gap` states in its own comment: a default lets a missed construction site render a booking as soft while `GET /bookings` reports it hard.

In `app/api/v1/schemas/booking.py`: the same `Optional[Literal["soft", "hard"]] = None` on `BookingCreate`, and `protection_level: Optional[str] = None` on `BookingResponse` and on `BookingRequestSummary`.

- [ ] **Step 4: Add the predicate and wire both create paths**

In `app/services/booking_request_service.py`, near the top-level helpers:

```python
from app.core.protection_levels import PROTECTION_LEVELS, PROTECTION_SOFT
from app.core.security import Role


def _may_set_protection(user: User) -> bool:
    """Admin, Release Manager, or a master admin acting in this tenant.

    Master admins are included for the reason contention_service._is_admin
    gives: the two places that forgot showed a master admin a control that
    403'd on click.
    """
    return (
        user.role in (Role.ADMIN, Role.RELEASE_MANAGER)
        or bool(user.is_master_admin)
    )


def assert_may_set_protection(
    user: User, *, submitted: Optional[str], current: str
) -> None:
    """Refuse a CHANGE of protection level by someone without the role.

    `current` is the value that would apply if the caller said nothing — the
    booking type's default on create, the stored value on update.

    THE UNCHANGED-VALUE CARVE-OUT IS LOAD-BEARING, NOT TIDY. The form shows a
    non-admin their level read-only and submits the whole form including it,
    so a bare role check breaks the primary create journey for every
    Developer and Test Manager. It is the same call B2's name rule made: the
    permission guards a CHANGE, not a MENTION.
    """
    if submitted is None or submitted == current:
        return
    if _may_set_protection(user):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "Only an Admin or Release Manager may change a booking's protection level",
    )
```

In `create_request`, after `initial_state` is loaded and before the `BookingRequest(...)` construction:

```python
    booking_type = (await db.execute(
        select(BookingType).where(
            BookingType.id == data["booking_type_id"],
            BookingType.tenant_id == tenant_id,
        )
    )).scalar_one_or_none()
    inherited = (
        booking_type.default_protection_level
        if booking_type is not None
        else PROTECTION_SOFT
    )
    submitted = data.get("protection_level")
    assert_may_set_protection(current_user, submitted=submitted, current=inherited)
    protection_level = submitted if submitted is not None else inherited
```

and pass `protection_level=protection_level` to the `BookingRequest(...)` call.

`_load_initial_state` already reads the booking type for its lifecycle template — if it can return the row rather than just the state without contorting its signature, do that instead of the second query and say so in a comment. If it cannot, leave the extra read: one query per create is not worth bending an existing helper out of shape.

In `app/services/booking_service.py`'s `create_booking`, apply the identical three lines beside the existing `exclusive_use_requested=data.exclusive_use`, reading `data.protection_level`.

- [ ] **Step 5: Populate the response fields**

In `app/api/v1/bookings.py::_to_response`, set `resp.protection_level = req.protection_level` next to the existing `resp.exclusive_use = req.exclusive_use_requested`. Do the same at **every** `EnvBookingSummary(...)` construction site — `grep -rn "EnvBookingSummary(" backend/app` lists them; A3 found six across two routers. A missed site is a Pydantic `ValidationError`, not a silent wrong answer, which is exactly why the field is required.

- [ ] **Step 6: Run to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: PASS, 9 tests.

- [ ] **Step 7: Run the affected subset (no full suite — see the revised cadence)**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q
cd backend && PYTHONPATH=. uv run pytest -q -k "booking or conflict or request"
```
Expected: PASS. Existing tests constructing `EnvBookingSummary` by keyword will fail until they pass the new required field — **fix them, do not default it.** The `-k` subset is chosen to reach every construction site: this task makes a schema field required, so the failures land in whichever files build that type, not in the files you edited.

Task 5 runs the full SQLite suite and Task 7 runs both engines; a regression this task introduces is caught there.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(b4): inherit protection level at create, gate changes on role"
```

---

## Task 3: The update path

**Files:**
- Modify: `backend/app/services/booking_request_service.py:325-360` (`STANDARD_REQUEST_FIELDS`, `update_standard_fields`)
- Modify: `backend/app/api/v1/schemas/booking_request.py` (`BookingRequestUpdate`)
- Test: `backend/tests/integration/test_protection_level_api.py`

**Interfaces:**
- Consumes: `assert_may_set_protection` from Task 2.
- Produces: `protection_level` accepted by `PATCH /booking-requests/{id}/standard-fields`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_an_admin_may_change_the_level_after_the_fact(
    client, auth_headers, soft_request
):
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=auth_headers,
        json={"protection_level": PROTECTION_HARD},
    )
    assert r.status_code == 200, r.text
    assert r.json()["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_a_developer_may_not_change_the_level(
    client, developer_headers, soft_request
):
    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={"protection_level": PROTECTION_HARD},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_a_full_form_save_resending_an_unchanged_level_is_accepted(
    client, developer_headers, db_session, soft_request
):
    """The carve-out on the UPDATE path.

    An Admin marks someone's booking hard. The original booker then saves the
    edit form, which resends every standard field including the level they
    cannot change. That save must succeed — otherwise an admin action makes a
    booking permanently unsavable by its own owner.
    """
    soft_request.protection_level = PROTECTION_HARD
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={
            "project_name": "Renamed by the booker",
            "protection_level": PROTECTION_HARD,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["project_name"] == "Renamed by the booker"
    assert r.json()["protection_level"] == PROTECTION_HARD


@pytest.mark.asyncio
async def test_omitting_the_level_leaves_it_alone(
    client, developer_headers, db_session, soft_request
):
    """`update_standard_fields` keys on the submitted key set — an omitted key
    means "leave alone", so only an explicit value can change anything."""
    soft_request.protection_level = PROTECTION_HARD
    await db_session.flush()

    r = await client.patch(
        f"/api/v1/booking-requests/{soft_request.id}/standard-fields",
        headers=developer_headers,
        json={"project_name": "Still fine"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["protection_level"] == PROTECTION_HARD
```

Add a `soft_request` fixture: a `BookingRequest` at `PROTECTION_SOFT` owned by the `developer_headers` user, with one `Booking` child.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q -k "change_the_level or unchanged_level or leaves_it_alone"`
Expected: FAIL — `protection_level` is rejected as an unknown standard field.

- [ ] **Step 3: Implement**

Add `"protection_level"` to `STANDARD_REQUEST_FIELDS`. Add `protection_level: Optional[Literal["soft", "hard"]] = None` to `BookingRequestUpdate`.

In `update_standard_fields`, after the `unknown` check and before any assignment:

```python
    if "protection_level" in values:
        assert_may_set_protection(
            current_user,
            submitted=values["protection_level"],
            current=req.protection_level,
        )
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: PASS, 13 tests.

- [ ] **Step 5: Mutation-check the carve-out across the whole file set**

Delete the `submitted == current` clause from `assert_may_set_protection`, run the **whole** B4 test set, and confirm a test fails. Then restore it.

B2 taught this precisely: its plan named the wrong test for its own carve-out, because a second mechanism (`data.name != env.name`) guarded the same branch and the named test stayed green. Here the second mechanism is `submitted is None`. **Run the mutation against every B4 file, not the one you expect.** Record in the commit message which test caught it.

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(b4): protection level editable by Admin/RM, unchanged value always accepted"
```

---

## Task 4: The verdict extension

**Files:**
- Modify: `backend/app/services/contention_service.py` (`_ranks_for`, `_decide`, `verdicts_for_pairs`, the outcome constants)
- Test: `backend/tests/services/test_protection_verdict.py`

**Interfaces:**
- Consumes: `PROTECTION_SOFT`, `PROTECTION_HARD` from Task 1; `BookingRequest.protection_level`.
- Produces: `contention_service.OUTCOME_PROTECTED = "protected"`; `_ranks_for` returning a **4-tuple** `(requested_project_id, resolved_project_id, priority_rank, protection_level)`; `ContentionVerdict` unchanged in shape.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_protection_verdict.py`:

```python
"""Phase 7 B4 — protection as the tie-break in A4's verdict.

RANK STAYS STRICTLY PRIMARY. Protection speaks only where rank cannot
separate the pair. Every test here that asserts a winner must be readable as
"and rank could not decide this".
"""
import pytest

from app.core.protection_levels import PROTECTION_HARD, PROTECTION_SOFT
from app.services import contention_service as cs


# (requested_project_id, resolved_project_id, priority_rank, protection_level)
def side(rank=None, project=None, level=PROTECTION_SOFT, requested=None):
    return (requested if requested is not None else project, project, rank, level)


def test_rank_still_decides_and_protection_is_not_consulted():
    """A SOFT booking on a better rank beats a HARD one. If this ever flips,
    B4 has stopped being additive and has reweighted A4."""
    v = cs._decide(
        1, side(rank=1, project=10, level=PROTECTION_SOFT),
        2, side(rank=5, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_RANKED
    assert v.winner_booking_id == 1
    assert v.reason == "the higher-priority project wins"


def test_equal_rank_is_broken_by_protection():
    v = cs._decide(
        1, side(rank=3, project=10, level=PROTECTION_SOFT),
        2, side(rank=3, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 2
    assert v.reason == (
        "both projects have the same priority rank; the protected booking holds"
    )


def test_unranked_is_broken_by_protection():
    v = cs._decide(
        1, side(rank=None, project=10, level=PROTECTION_HARD),
        2, side(rank=4, project=20, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one project has no priority rank; the protected booking holds"
    )


def test_no_project_is_broken_by_protection():
    v = cs._decide(
        1, side(project=None, level=PROTECTION_HARD),
        2, side(project=None, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one booking is not linked to a project; "
        "the protected booking holds"
    )


def test_an_unresolvable_project_keeps_its_own_reason_when_protection_speaks():
    """A4's second no_project reason exists so a user staring at an archived
    project's name is told the real problem. Composing must not lose it."""
    v = cs._decide(
        1, side(project=None, requested=99, level=PROTECTION_HARD),
        2, side(project=None, level=PROTECTION_SOFT),
    )
    assert v.outcome == cs.OUTCOME_PROTECTED
    assert v.winner_booking_id == 1
    assert v.reason == (
        "at least one booking's project is archived or belongs to another "
        "tenant; the protected booking holds"
    )


@pytest.mark.parametrize(
    "a,b",
    [
        (side(rank=3, project=10), side(rank=3, project=20)),
        (side(rank=None, project=10), side(rank=2, project=20)),
        (side(project=None), side(project=None)),
    ],
)
def test_equal_levels_change_nothing(a, b):
    """THE MIGRATION IS INERT. Every existing row is 'soft', so every pair is
    soft-vs-soft and every verdict is exactly what A4 rendered before B4.

    This is the test that fails if someone later "simplifies" the protection
    branch to fire on equality rather than on difference."""
    v = cs._decide(1, a, 2, b)
    assert v.outcome in (cs.OUTCOME_EQUAL_RANK, cs.OUTCOME_UNRANKED, cs.OUTCOME_NO_PROJECT)
    assert v.winner_booking_id is None
    assert "protected" not in v.reason


def test_an_unknown_level_never_loses():
    """A booking absent from `_ranks_for` — another tenant's, or stale — has a
    level of None, not 'soft'. Defaulting the sentinel to 'soft' is the
    obvious implementation and it silently makes every unresolvable booking
    lose to any hard one."""
    v = cs._decide(
        1, (None, None, None, None),
        2, side(project=None, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_NO_PROJECT
    assert v.winner_booking_id is None


def test_both_hard_has_no_winner():
    v = cs._decide(
        1, side(rank=3, project=10, level=PROTECTION_HARD),
        2, side(rank=3, project=20, level=PROTECTION_HARD),
    )
    assert v.outcome == cs.OUTCOME_EQUAL_RANK
    assert v.winner_booking_id is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_protection_verdict.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'OUTCOME_PROTECTED'`

- [ ] **Step 3: Implement**

Add beside the other outcome constants in `contention_service.py`:

```python
# B4's tie-break. THE FIRST OUTCOME WITH A WINNER THAT RANK DID NOT CHOOSE.
#
# A4's spec declined a fifth outcome for "project not resolvable" on the
# grounds that a malformed link "is not a different KIND of answer". This one
# IS: rank could not separate the pair, and something else did. It is
# deliberately not folded into OUTCOME_RANKED, whose reason claims a
# higher-priority project won — which here is false and would be read as one.
OUTCOME_PROTECTED = "protected"

# Appended to whichever no-winner reason applied, so the RANK FACT SURVIVES.
# A bare "the protected booking holds" throws away the only thing that tells
# an admin whether to go and set a rank.
PROTECTED_SUFFIX = "; the protected booking holds"
```

Add a helper immediately above `_decide`:

```python
def _protection_breaks_tie(
    a_id: int, a_level: Optional[str], b_id: int, b_level: Optional[str], reason: str
) -> Optional[ContentionVerdict]:
    """The hard side wins, or None if protection has nothing to say.

    BOTH LEVELS MUST BE KNOWN. A booking we cannot see (absent from
    `_ranks_for` — another tenant's, or stale) carries None, and must not be
    declared the loser on the strength of a level nobody read.
    """
    if a_level is None or b_level is None or a_level == b_level:
        return None
    winner = a_id if a_level == PROTECTION_HARD else b_id
    return ContentionVerdict(OUTCOME_PROTECTED, winner, reason + PROTECTED_SUFFIX)
```

Widen `_ranks_for`'s select and return, adding `BookingRequest.protection_level` to the existing `select(...)` — **no new join, no second query**:

```python
        select(
            Booking.id,
            BookingRequest.project_id,
            Project.id,
            Project.priority_rank,
            BookingRequest.protection_level,
        )
```
```python
    return {
        bid: (requested, pid, rank, level)
        for bid, requested, pid, rank, level in rows
    }
```

and update its return annotation and its docstring's first line to name four values.

In `_decide`, unpack four values per side and consult protection in each no-winner branch, **keeping the branch order exactly as it is**:

```python
    a_requested, a_project, a_rank, a_level = a
    b_requested, b_project, b_rank, b_level = b
    if a_project is None or b_project is None:
        unresolvable = (a_requested is not None and a_project is None) or (
            b_requested is not None and b_project is None
        )
        reason = REASON_PROJECT_UNRESOLVABLE if unresolvable else REASON_NO_PROJECT
        return (
            _protection_breaks_tie(a_id, a_level, b_id, b_level, reason)
            or ContentionVerdict(OUTCOME_NO_PROJECT, None, reason)
        )
    if a_rank is None or b_rank is None:
        reason = "at least one project has no priority rank"
        return (
            _protection_breaks_tie(a_id, a_level, b_id, b_level, reason)
            or ContentionVerdict(OUTCOME_UNRANKED, None, reason)
        )
    if a_rank == b_rank:
        reason = "both projects have the same priority rank"
        return (
            _protection_breaks_tie(a_id, a_level, b_id, b_level, reason)
            or ContentionVerdict(OUTCOME_EQUAL_RANK, None, reason)
        )
    winner = a_id if a_rank < b_rank else b_id  # LOWER WINS
    return ContentionVerdict(OUTCOME_RANKED, winner, "the higher-priority project wins")
```

In `verdicts_for_pairs`, widen the sentinel and say why:

```python
    # Four Nones, and the LAST one matters: an unknown protection level must
    # never lose. See _protection_breaks_tie.
    missing = (None, None, None, None)
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/services/test_protection_verdict.py -q`
Expected: PASS, 10 tests (the parametrize contributes 3).

- [ ] **Step 5: Run A4's existing tests unchanged**

Run: `cd backend && PYTHONPATH=. uv run pytest tests -q -k "contention or escalation"`
Expected: PASS with **no edits to those files**. If any A4 test needed changing, B4 has stopped being additive — stop and re-read the spec's "The verdict extension".

- [ ] **Step 6: Mutation-check the four rules**

One at a time, break it, run `pytest tests/services/test_protection_verdict.py -q`, confirm a **named** test fails, restore:
1. Make `_protection_breaks_tie` fire on `a_level == b_level`.
2. Change the `missing` sentinel's last element to `PROTECTION_SOFT`.
3. Consult protection in the `ranked` branch too.
4. Drop `PROTECTED_SUFFIX` and return a bare `"the protected booking holds"`.

A rule the code explains at length reads as a rule that is guarded, and usually is not — six of seven mutation survivors on A4 were exactly such sentences.

- [ ] **Step 7: Run the affected subset, then commit**

`_decide` is pure Python over tuples — no SQL, no dialect exposure — so the focused file plus the contention subset is the right gate here. `_ranks_for`'s widened `select` IS SQL, and Task 5's full SQLite run and Task 7's dual-engine run cover it.

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_protection_verdict.py -q
cd backend && PYTHONPATH=. uv run pytest -q -k "contention or escalation or booking"
git add backend/app/services/contention_service.py backend/tests/services/test_protection_verdict.py
git commit -m "feat(b4): protection breaks the tie where rank cannot separate a contention"
```

---

## Task 5: The list filter and the sort

**Files:**
- Modify: `backend/app/api/v1/bookings.py:33` (`BOOKING_SORTS`), `:166+` (`list_bookings`)
- Modify: `backend/app/services/booking_service.py` (`list_bookings`)
- Test: `backend/tests/integration/test_protection_level_api.py`

**Interfaces:**
- Consumes: `BookingRequest.protection_level`.
- Produces: `GET /bookings?protection=soft|hard`; `BOOKING_SORTS["protection_level"]`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_protection_filter_runs_in_sql_before_the_window(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    """X-Total-Count must describe the FILTERED set, not the page and not the
    unfiltered total — otherwise the grid's footer lies and its paging is
    windowing the wrong result set."""
    r = await client.get(
        "/api/v1/bookings/?protection=hard&limit=2", headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.headers["X-Total-Count"] == "3"
    assert len(r.json()) == 2
    assert all(b["protection_level"] == PROTECTION_HARD for b in r.json())


@pytest.mark.asyncio
async def test_omitting_the_filter_returns_both(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    r = await client.get("/api/v1/bookings/?limit=100", headers=auth_headers)
    assert r.headers["X-Total-Count"] == "28"


@pytest.mark.asyncio
async def test_an_empty_protection_param_is_a_422_not_an_ignored_one(
    client, auth_headers
):
    """Nothing may ever emit `?protection=`. The UI spells no-selection as an
    OMITTED KEY (`any` in the URL, mapped to undefined), never `all` —
    buildParams' own sentinel — and never ''."""
    r = await client.get("/api/v1/bookings/?protection=", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_protection_value_is_a_422(client, auth_headers):
    r = await client.get("/api/v1/bookings/?protection=granite", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sorting_by_protection_orders_rendered_rows(
    client, auth_headers, soft_bookings_25, hard_bookings_3
):
    """Assert RENDERED ROW ORDER, never the emitted SQL token — the pagination
    pilot pinned the token and stayed green while users saw the wrong order."""
    r = await client.get(
        "/api/v1/bookings/?sort_by=protection_level&sort_dir=asc&limit=100",
        headers=auth_headers,
    )
    levels = [b["protection_level"] for b in r.json()]
    assert levels == sorted(levels)
    assert levels[0] == PROTECTION_HARD  # 'hard' < 'soft'


@pytest.mark.asyncio
async def test_an_unknown_sort_by_is_a_422_not_a_silent_fallback(
    client, auth_headers
):
    r = await client.get("/api/v1/bookings/?sort_by=protection", headers=auth_headers)
    assert r.status_code == 422
```

Add `soft_bookings_25` and `hard_bookings_3` fixtures creating that many bookings in the tenant.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q -k "protection_filter or omitting_the_filter or empty_protection or unknown_protection or sorting_by_protection or unknown_sort"`
Expected: FAIL — `protection` is dropped as an unknown param (FastAPI drops unknown query params **silently**, so the filter test fails on the count, not on a 4xx).

- [ ] **Step 3: Implement**

`app/api/v1/bookings.py` — add to `BOOKING_SORTS`:

```python
    # B4. SORTABLE, unlike `agreement_gap`: this is a stored column on the
    # joined booking_request, not a value resolved after the page is fetched.
    # It is therefore not a member of docs/pagination.md's permanently-
    # unsortable set.
    "protection_level": BookingRequest.protection_level,
```

Import `BookingRequest` in `bookings.py` if it is not already imported.

Add the query parameter to `list_bookings`, mirroring `agreement_gap`'s declaration:

```python
    protection: Optional[Literal["soft", "hard"]] = Query(
        None,
        description=(
            "Only bookings whose request declares this protection level. "
            "OMIT the key for no filter — an empty value is a 422, not an "
            "ignored param."
        ),
    ),
```

and pass it through to `booking_service.list_bookings`.

In `booking_service.list_bookings`, apply it **to the existing `BookingRequest` join**:

```python
    if protection is not None:
        query = query.where(BookingRequest.protection_level == protection)
```

**Both list filters hang off ONE join.** A3 established this: the pre-branch shape was a join per filter, and restoring it breaks exactly the pair the project rollup sends while every single-filter test stays green. Do not add a second join for this.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: PASS, 19 tests.

- [ ] **Step 5: Check the filter combines with the existing ones**

Add and run:

```python
@pytest.mark.asyncio
async def test_protection_and_project_filters_combine(
    client, auth_headers, hard_bookings_3, project
):
    r = await client.get(
        f"/api/v1/bookings/?protection=hard&project_id={project.id}&limit=100",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
```

Expected: PASS, and no `sqlalchemy` duplicate-join warning in the output.

- [ ] **Step 6: Full SQLite suite, then commit**

This task adds a `WHERE` and an `ORDER BY`, so it is one of the three that keeps a full run. **SQLite only** — the PostgreSQL leg is Task 7's, and CI runs both on push.

Launch it in the background with a fixed log path and wait with an `until` loop; it takes ~16 minutes and exceeds the foreground limit.

```bash
cd backend && PYTHONPATH=. uv run pytest -q > <tasks-dir>/t5-sqlite.log 2>&1   # run_in_background
until grep -qE "[0-9]+ (passed|failed)" <tasks-dir>/t5-sqlite.log; do sleep 20; done
git add backend/app backend/tests
git commit -m "feat(b4): ?protection= filter in SQL and a sortable protection column"
```

---

## Task 6: Booking-type defaults through the API

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py:266-292`
- Modify: `backend/app/api/v1/booking_lifecycle.py` (the booking-type create/update handlers)
- Test: `backend/tests/integration/test_protection_level_api.py`

**Interfaces:**
- Consumes: the two `BookingType` columns from Task 1.
- Produces: `default_protection_level` and `default_duration_minutes` on `BookingTypeCreate`, `BookingTypeUpdate`, `BookingTypeResponse`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_a_booking_types_defaults_round_trip(
    client, auth_headers, lifecycle_template
):
    """A4's ProjectCreate silently DISCARDED priority_rank because the schema
    had neither the field nor extra="forbid", and only a browser pass caught
    it. Read every field back through the API, not off the model."""
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Release cycle",
            "lifecycle_template_id": lifecycle_template.id,
            "default_protection_level": PROTECTION_HARD,
            "default_duration_minutes": 20160,
        },
    )
    assert r.status_code in (200, 201), r.text
    created = r.json()
    assert created["default_protection_level"] == PROTECTION_HARD
    assert created["default_duration_minutes"] == 20160

    listed = (await client.get("/api/v1/tenant/booking-types", headers=auth_headers)).json()
    mine = [t for t in listed if t["id"] == created["id"]][0]
    assert mine["default_protection_level"] == PROTECTION_HARD
    assert mine["default_duration_minutes"] == 20160


@pytest.mark.asyncio
async def test_an_unknown_key_on_a_booking_type_is_refused(
    client, auth_headers, lifecycle_template
):
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Typo'd",
            "lifecycle_template_id": lifecycle_template.id,
            "default_protection": PROTECTION_HARD,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_duration_must_be_positive(client, auth_headers, lifecycle_template):
    r = await client.post(
        "/api/v1/tenant/booking-types",
        headers=auth_headers,
        json={
            "name": "Nonsense",
            "lifecycle_template_id": lifecycle_template.id,
            "default_duration_minutes": 0,
        },
    )
    assert r.status_code == 422
```

Confirm the booking-types route prefix in `backend/app/api/v1/booking_lifecycle.py` and use the real one.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q -k "booking_type"`
Expected: FAIL — the fields come back absent, and the typo'd key is accepted and dropped.

- [ ] **Step 3: Implement**

```python
class BookingTypeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: Optional[str] = None
    lifecycle_template_id: int
    color: Optional[str] = None
    is_active: bool = True
    default_protection_level: Literal["soft", "hard"] = "soft"
    # None means "no preset". `gt=0` because a zero-minute slot would fill the
    # form with a zero-length booking, which conflicts with nothing at all —
    # overlap is `start < end AND end > start`.
    default_duration_minutes: Optional[int] = Field(default=None, gt=0)


class BookingTypeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    lifecycle_template_id: Optional[int] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None
    default_protection_level: Optional[Literal["soft", "hard"]] = None
    default_duration_minutes: Optional[int] = Field(default=None, gt=0)


class BookingTypeResponse(BaseModel):
    ...  # existing fields unchanged
    default_protection_level: str
    default_duration_minutes: Optional[int]
```

Add `Literal` and `Field` / `ConfigDict` imports as needed. Wire both new fields through the create and update handlers in `booking_lifecycle.py` — **check how the update handler applies its fields.** If it iterates `model_dump(exclude_unset=True)` the new keys flow automatically; if it assigns field by field, add them explicitly, and note that `default_duration_minutes=None` then cannot clear a preset. If it cannot clear, say so in a comment rather than leaving it ambiguous.

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q`
Expected: PASS, 23 tests.

- [ ] **Step 5: Run the affected subset, then commit**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_protection_level_api.py -q
cd backend && PYTHONPATH=. uv run pytest -q -k "booking_type or lifecycle"
git add backend/app backend/tests
git commit -m "feat(b4): booking-type protection and duration defaults through the API"
```

---

## Task 7: The guard on the promise

**Files:**
- Create: `backend/tests/test_b4_advises_never_blocks.py`

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: nothing. This task adds no production code. If you find yourself writing any, the design has drifted.

- [ ] **Step 1: Write the test file**

```python
"""B4 ADVISES; IT NEVER BLOCKS AND IT NEVER PREEMPTS.

The fourth sub-project running whose central promise is a named test rather
than an absence in the diff — after A1's
test_an_agreement_changes_no_booking_behaviour, A4's
test_a_contention_changes_no_booking_behaviour and B2's
test_b2_advises_never_blocks.

IF ANY TEST HERE FAILS, B4 HAS STARTED ACTING. Do not "fix" it by relaxing the
assertion.
"""
import pytest

from app.core.protection_levels import PROTECTION_HARD, PROTECTION_SOFT
from app.services import booking_service


@pytest.mark.asyncio
async def test_a_soft_booking_may_be_made_over_a_hard_one(
    client, auth_headers, hard_booking, environment
):
    """The whole point. A hard reservation is DECLARED protected, not
    mechanically protected."""
    r = await client.post(
        "/api/v1/booking-requests/",
        headers=auth_headers,
        json={
            "project_name": "Booked right over the top",
            "booking_type_id": hard_booking.booking_request.booking_type_id,
            "start_date": hard_booking.start_date.isoformat(),
            "end_date": hard_booking.end_date.isoformat(),
            "environment_ids": [environment.id],
        },
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_check_overlap_answers_identically_for_both_levels(
    db_session, tenant, environment, soft_booking, hard_booking
):
    """`check_overlap` must not have learned about protection. Its answer is a
    function of dates, tenant, status and exclusive use — nothing else."""
    soft = await booking_service.check_overlap(
        db_session, environment.id, soft_booking.start_date,
        soft_booking.end_date, tenant.id, exclusive_use=False,
    )
    hard = await booking_service.check_overlap(
        db_session, environment.id, hard_booking.start_date,
        hard_booking.end_date, tenant.id, exclusive_use=False,
    )
    assert soft.blocked == hard.blocked is False


@pytest.mark.asyncio
async def test_a_hard_booking_is_still_transitionable(
    client, auth_headers, hard_booking
):
    allowed = (await client.get(
        f"/api/v1/bookings/{hard_booking.id}/allowed-transitions",
        headers=auth_headers,
    )).json()
    assert allowed, "a hard booking with no allowed transitions is a blocked one"


@pytest.mark.asyncio
async def test_a_hard_booking_is_still_editable(client, auth_headers, hard_booking):
    r = await client.patch(
        f"/api/v1/booking-requests/{hard_booking.booking_request_id}/standard-fields",
        headers=auth_headers,
        json={"notes": "still editable"},
    )
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_recording_a_contention_decision_still_changes_no_booking(
    db_session, hard_booking, soft_booking
):
    """A4's guard, re-asserted with protection in play: the verdict now names a
    winner in cases it previously could not, and that must still move nothing."""
    before = [
        (b.status, b.start_date, b.end_date, b.deleted_at)
        for b in (hard_booking, soft_booking)
    ]
    from app.services import contention_service as cs
    await cs.verdict_for_pair(
        db_session, hard_booking.id, soft_booking.id, hard_booking.tenant_id
    )
    await db_session.refresh(hard_booking)
    await db_session.refresh(soft_booking)
    after = [
        (b.status, b.start_date, b.end_date, b.deleted_at)
        for b in (hard_booking, soft_booking)
    ]
    assert before == after


def test_no_production_module_refuses_on_a_protection_level():
    """A structural assertion, deliberately — there is no behavioural test for
    "nobody anywhere raises on this value", and a grep is the only thing that
    covers code paths no fixture reaches.

    Same class of exception as the health-history tiebreaker's structural
    assertion, and documented here for the same reason.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"protection_level", text):
            window = text[max(0, match.start() - 400) : match.end() + 400]
            if "HTTPException" in window and "403" not in window:
                offenders.append(f"{path}:{text[:match.start()].count(chr(10)) + 1}")
    assert not offenders, (
        "B4 may only ever raise 403 on a protection level (the role gate). "
        f"Found a refusal near: {offenders}"
    )
```

Add `soft_booking` and `hard_booking` fixtures — one `Booking` each, on the same environment and overlapping dates, whose parent requests carry the two levels.

- [ ] **Step 2: Run it**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_b4_advises_never_blocks.py -q`
Expected: PASS, 6 tests. If any fails, the failure is the finding — fix the production code, not the test.

- [ ] **Step 3: Prove the file is not vacuous**

Insert a real refusal into `booking_request_service.create_request` — raise a 409 when any overlapping booking's request is `hard` — and confirm `test_a_soft_booking_may_be_made_over_a_hard_one` **fails**. Then remove it.

A1 proved its equivalent guard this way and it is the only thing that distinguishes a promise-keeping test from a test that would pass against an empty codebase. Record the result in the commit message.

- [ ] **Step 4: Both engines, then commit**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q
git add backend/tests/test_b4_advises_never_blocks.py
git commit -m "test(b4): the guard — B4 advises, never blocks, never preempts"
```

---

## Task 8: Frontend types, constants, and the admin panel

**Files:**
- Create: `frontend/src/constants/protection.ts`
- Modify: `frontend/src/types/bookingRequest.ts`, `src/types/booking.ts`, `src/types/bookingLifecycle.ts`, `src/components/admin/BookingTypesPanel.tsx`
- Test: `frontend/src/components/admin/__tests__/bookingTypeDefaults.test.tsx`

**Interfaces:**
- Consumes: the Task 6 API shape.
- Produces: `PROTECTION_LEVELS: readonly ['soft','hard']`, `PROTECTION_LABELS: Record<string,string>`, `PROTECTION_FILTER_NONE = 'any'`, `ProtectionLevel` type.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import BookingTypesPanel from '../BookingTypesPanel';
// Follow the render/store harness the other admin-panel tests in this
// directory use — do not invent a new one.

describe('BookingTypesPanel — B4 defaults', () => {
  it('sends both defaults when a booking type is created', async () => {
    const post = vi.fn().mockResolvedValue({ data: { id: 7 } });
    // wire `post` into the api mock exactly as the sibling tests do
    render(<BookingTypesPanel />);
    await userEvent.type(screen.getByLabelText(/name/i), 'Release cycle');
    await userEvent.click(screen.getByLabelText(/protection/i));
    await userEvent.click(screen.getByRole('option', { name: /protected/i }));
    await userEvent.type(screen.getByLabelText(/default duration/i), '20160');
    await userEvent.click(screen.getByRole('button', { name: /^add$/i }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        expect.stringContaining('booking-types'),
        expect.objectContaining({
          default_protection_level: 'hard',
          default_duration_minutes: 20160,
        }),
      ),
    );
  });

  it('sends null rather than 0 when the duration is left blank', async () => {
    // A blank TextField yields '', and Number('') is 0 — which the API 422s
    // on `gt=0`. The panel must map blank to null.
  });
});
```

Fill the second test in fully, following the first.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/bookingTypeDefaults.test.tsx`
Expected: FAIL — no protection control exists.

- [ ] **Step 3: Implement**

`frontend/src/constants/protection.ts`:

```ts
/**
 * How hard a booking's claim on an environment is (Phase 7 B4).
 *
 * NOT the same axis as `exclusive_use_requested`. Exclusive use asks "can
 * anyone else be in here with me"; this asks "can I be pushed out".
 *
 * B4 ADVISES: nothing in the UI may disable a control, hide an action or
 * refuse a submit on the strength of this value. It is rendered, it is
 * filtered on, and it appears in A4's verdict. That is all.
 */
export const PROTECTION_LEVELS = ['soft', 'hard'] as const;
export type ProtectionLevel = (typeof PROTECTION_LEVELS)[number];

export const PROTECTION_LABELS: Record<ProtectionLevel, string> = {
  soft: 'Preemptible',
  hard: 'Protected',
};

/**
 * The URL's spelling of "no protection filter". `any`, NEVER `all` — `all` is
 * `buildParams`' own no-selection sentinel, so a vocabulary containing it
 * builds byte-identical params for two different states and the grid never
 * refetches. Third sub-project to hit this (A3, A4, B2).
 */
export const PROTECTION_FILTER_NONE = 'any';
```

Add `protection_level: ProtectionLevel` to the booking-request and booking types, and `default_protection_level: ProtectionLevel; default_duration_minutes: number | null` to the booking-type type.

In `BookingTypesPanel.tsx`, add a `Select` (labelled "Protection") and a numeric `TextField` (labelled "Default duration (minutes)") to **both** the add row and the edit dialog, and include both in the `post`/`patch` payloads at lines ~64 and ~97. Map a blank duration to `null`, never `0`. Add a `Protection` column to the grid.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/bookingTypeDefaults.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(b4): protection constants, types, and booking-type defaults in the admin panel"
```

---

## Task 9: The duration helper and the booking form

**Files:**
- Create: `frontend/src/utils/duration.ts`, `frontend/src/utils/__tests__/duration.test.ts`
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`
- Test: `frontend/src/pages/bookings/__tests__/bookingFormProtection.test.tsx`

**Interfaces:**
- Consumes: `PROTECTION_LABELS`, the booking-type defaults.
- Produces: `addDuration(start: Date, minutes: number): Date`.

- [ ] **Step 1: Write the failing helper test**

```ts
import { describe, expect, it } from 'vitest';
import { addDuration } from '../duration';

describe('addDuration', () => {
  it('adds a sub-day duration as minutes', () => {
    const start = new Date('2026-09-01T09:00:00Z');
    expect(addDuration(start, 240).toISOString()).toBe('2026-09-01T13:00:00.000Z');
  });

  it('adds a whole-day multiple as CALENDAR days, so the wall clock holds across DST', () => {
    // Europe/London springs forward at 01:00 on 2026-03-29. Adding 20160
    // minutes as an instant offset would land an hour early on the wall
    // clock; adding 14 calendar days keeps 09:00 at 09:00.
    //
    // This codebase has already paid twice for instant-vs-calendar
    // arithmetic: formatExpiry reported an environment "overdue by 1 day"
    // throughout the day it expired, and SP5a's utilization needed per-date
    // localization to be DST-correct.
    process.env.TZ = 'Europe/London';
    const start = new Date(2026, 2, 20, 9, 0, 0); // 20 Mar 2026, 09:00 local
    const end = addDuration(start, 20160); // 14 days
    expect(end.getHours()).toBe(9);
    expect(end.getDate()).toBe(3); // 3 April
  });

  it('leaves the start untouched', () => {
    const start = new Date('2026-09-01T09:00:00Z');
    addDuration(start, 240);
    expect(start.toISOString()).toBe('2026-09-01T09:00:00.000Z');
  });
});
```

Set `TZ` via vitest config or an `environmentOptions` entry rather than mid-test if this repo's setup requires it — check `frontend/vitest.config.ts` first.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/utils/__tests__/duration.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper**

```ts
const MINUTES_PER_DAY = 1440;

/**
 * `start` plus `minutes`, applied by rule rather than by arithmetic.
 *
 * A whole multiple of a day is added as CALENDAR days; anything else as
 * minutes. So "sprint = 14 days" from 09:00 lands on 09:00 across a
 * spring-forward, while "half-day = 240" from 09:00 lands on 13:00.
 *
 * Returns a new Date; never mutates `start`.
 */
export function addDuration(start: Date, minutes: number): Date {
  const out = new Date(start.getTime());
  if (minutes > 0 && minutes % MINUTES_PER_DAY === 0) {
    out.setDate(out.getDate() + minutes / MINUTES_PER_DAY);
    return out;
  }
  out.setTime(out.getTime() + minutes * 60_000);
  return out;
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/utils/__tests__/duration.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Write the failing form test**

Create `frontend/src/pages/bookings/__tests__/bookingFormProtection.test.tsx`. Copy the `vi.mock` block and the `renderForm()` helper from `bookingFormGroups.test.tsx` **verbatim** (lines 1–60 and ~194) — same service mocks, same `Provider store` + `MemoryRouter` wrapper — then:

```tsx
import { setCredentials } from '../../../store/authSlice';
import { store } from '../../../store';

/** Seed the real store's auth state — the form reads `s.auth.user`. */
function signInAs(role: string) {
  store.dispatch(
    setCredentials({
      user: {
        id: 1,
        username: 'tester',
        email: 'tester@test.com',
        role,
        tenant_id: 1,
        is_active: true,
        is_master_admin: false,
      } as never,
      token: 'test-token',
    }),
  );
}

const HALF_DAY = {
  id: 1,
  name: 'Half day',
  lifecycle_template_id: 1,
  is_active: true,
  color: null,
  default_protection_level: 'soft',
  default_duration_minutes: 240,
} as never;

const RELEASE_CYCLE = {
  id: 2,
  name: 'Release cycle',
  lifecycle_template_id: 1,
  is_active: true,
  color: null,
  default_protection_level: 'hard',
  default_duration_minutes: 20160,
} as never;

describe('BookingForm — B4', () => {
  beforeEach(() => {
    vi.mocked(bookingLifecycleService.listBookingTypes).mockResolvedValue([
      HALF_DAY,
      RELEASE_CYCLE,
    ]);
    vi.mocked(environmentService.listEnvironments).mockResolvedValue({
      items: [{ id: 10, name: 'SIT' } as never],
      total: 1,
    } as never);
  });

  it('fills the end date from the booking type preset', async () => {
    signInAs('Admin');
    renderForm();
    await userEvent.type(screen.getByLabelText(/start/i), '2026-09-01T09:00');
    await userEvent.click(screen.getByLabelText(/booking type/i));
    await userEvent.click(screen.getByRole('option', { name: 'Half day' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/end/i)).toHaveValue('2026-09-01T13:00'),
    );
  });

  it('does NOT overwrite an end date the user already edited', async () => {
    // A preset that clobbers a deliberate choice is worse than no preset.
    signInAs('Admin');
    renderForm();
    await userEvent.type(screen.getByLabelText(/start/i), '2026-09-01T09:00');
    await userEvent.type(screen.getByLabelText(/end/i), '2026-09-30T17:00');
    await userEvent.click(screen.getByLabelText(/booking type/i));
    await userEvent.click(screen.getByRole('option', { name: 'Half day' }));

    await waitFor(() =>
      expect(screen.getByLabelText(/end/i)).toHaveValue('2026-09-30T17:00'),
    );
  });

  it('shows a non-admin their inherited level read-only, not hidden', async () => {
    // A user should be able to SEE that their release-cycle booking is
    // protected, even though they cannot change it.
    signInAs('Developer');
    renderForm();
    await userEvent.click(screen.getByLabelText(/booking type/i));
    await userEvent.click(screen.getByRole('option', { name: 'Release cycle' }));

    const control = await screen.findByLabelText(/protection/i);
    expect(control).toBeInTheDocument();
    expect(screen.getByText('Protected')).toBeInTheDocument();
    expect(control).toHaveAttribute('aria-disabled', 'true');
  });

  it('lets an Admin choose a level', async () => {
    signInAs('Admin');
    renderForm();
    await userEvent.click(screen.getByLabelText(/booking type/i));
    await userEvent.click(screen.getByRole('option', { name: 'Half day' }));
    await userEvent.click(screen.getByLabelText(/protection/i));
    await userEvent.click(screen.getByRole('option', { name: 'Protected' }));

    expect(screen.getByLabelText(/protection/i)).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(screen.getByText('Protected')).toBeInTheDocument();
  });

  it('submits the inherited level unchanged for a non-admin', async () => {
    // THE CARVE-OUT'S UI HALF. The form sends protection_level even when the
    // user cannot change it, and the server accepts it because it matches the
    // booking type's default. If this stops being sent, the backend carve-out
    // is untested from the side that actually exercises it.
    signInAs('Developer');
    renderForm();
    await userEvent.type(screen.getByLabelText(/start/i), '2026-09-01T09:00');
    await userEvent.click(screen.getByLabelText(/booking type/i));
    await userEvent.click(screen.getByRole('option', { name: 'Release cycle' }));
    await userEvent.click(screen.getByRole('button', { name: /create|submit/i }));

    await waitFor(() =>
      expect(bookingRequestService.create).toHaveBeenCalledWith(
        expect.objectContaining({ protection_level: 'hard' }),
      ),
    );
  });
});
```

Adjust the field label regexes and the submit button's name to whatever `BookingForm.tsx` actually renders — read it before writing, do not guess.

- [ ] **Step 6: Run to verify they fail, then implement**

Add to `BookingForm.tsx`: `protectionLevel` in the zod schema and defaults; an effect that fills `endDate` via `addDuration` when `bookingTypeId` changes **and** the user has not touched the end field (track that with a ref, not by comparing values); a *Sharing & protection* `<Box>` grouping the existing `exclusiveUse` control at line ~523 with the new one, each with helper text distinguishing them; and `protection_level: values.protectionLevel` in the submit payload at line ~279.

Helper text, verbatim:
- Exclusive use — "Nobody else may book this environment for the same window."
- Protection — "A protected booking holds its place when priority cannot separate two claims. It does not stop anyone booking over it."

- [ ] **Step 7: Run to verify they pass, then commit**

```bash
cd frontend && npx vitest run src/utils src/pages/bookings
git add frontend/src
git commit -m "feat(b4): duration presets and the sharing & protection group on the booking form"
```

---

## Task 10: The datetime-local fix

**Files:**
- Modify: `frontend/src/components/bookings/EditStandardFieldsDialog.tsx:160-179`, `frontend/src/pages/bookings/BookingDetail.tsx:719-728`
- Test: `frontend/src/components/bookings/__tests__/editStandardFieldsDates.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. A defect fix, in scope because B4's own feature is otherwise destroyed by the app's own edit path.

- [ ] **Step 1: Write the failing test**

```tsx
/**
 * TODAY both fields are `type="date"`, so a 09:00–13:00 booking renders as
 * "2026-09-01" twice and saving sends 00:00–00:00 — a ZERO-LENGTH booking,
 * which then conflicts with nothing at all, because overlap is
 * `start < end AND end > start` and a zero-length interval satisfies neither.
 * Rare while bookings are day-scale by habit; routine the moment B4 ships
 * half-day presets.
 */
const onSave = vi.fn();

function renderDialog() {
  return render(
    <Provider store={store}>
      <EditStandardFieldsDialog
        open
        onClose={vi.fn()}
        onSave={onSave}
        booking={
          {
            id: 1,
            start_date: '2026-09-01T09:00:00Z',
            end_date: '2026-09-01T13:00:00Z',
            booking_request_id: 1,
          } as never
        }
      />
    </Provider>,
  );
}

it('renders the time of day, not just the date', async () => {
  renderDialog();
  expect(screen.getByLabelText(/start date/i)).toHaveValue('2026-09-01T09:00');
  expect(screen.getByLabelText(/end date/i)).toHaveValue('2026-09-01T13:00');
});

it('saves a window that is not zero-length', async () => {
  renderDialog();
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  await waitFor(() => expect(onSave).toHaveBeenCalled());
  const payload = onSave.mock.calls[0][0];
  expect(payload.start_date).not.toBe(payload.end_date);
  expect(new Date(payload.end_date).getTime()).toBeGreaterThan(
    new Date(payload.start_date).getTime(),
  );
});
```

Read `EditStandardFieldsDialog.tsx`'s actual props (it takes the booking plus the field-permission map) and the save callback's real name before writing this — the shape above is the contract to assert, not necessarily the exact prop names. The dialog is timezone-sensitive: pin `TZ` in the test the way Task 9's duration test does, or the expected `09:00` becomes whatever the runner's zone makes of `09:00Z`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/components/bookings/__tests__/editStandardFieldsDates.test.tsx`
Expected: FAIL — the value is date-only and the saved window is zero-length.

- [ ] **Step 3: Implement**

Change both `type="date"` fields in `EditStandardFieldsDialog.tsx` and both in `BookingDetail.tsx` to `type="datetime-local"`, and fix the value formatting on each side: `datetime-local` wants `YYYY-MM-DDTHH:mm` in **local** time, so parse the ISO string to a `Date` and format it, rather than slicing the string. Put that conversion in one small local helper used by all four fields — four copies of a date-format expression is how the two halves drift apart.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/components/bookings src/pages/bookings`
Expected: PASS. Existing tests asserting a date-only value will fail — update them; they were pinning the defect.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "fix(b4): editing a booking no longer truncates its times to a zero-length window"
```

---

## Task 11: The list column and filter

**Files:**
- Modify: `frontend/src/pages/bookings/BookingList.tsx`, `frontend/src/constants/sortWhitelists.json`
- Test: `frontend/src/pages/bookings/__tests__/bookingListProtection.test.tsx`

**Interfaces:**
- Consumes: `PROTECTION_LABELS`, `PROTECTION_FILTER_NONE`, `GET /bookings?protection=`.
- Produces: `apiProtection(urlValue: string | number | undefined): 'soft' | 'hard' | undefined`.

- [ ] **Step 1: Write the failing tests**

```tsx
describe('BookingList — B4 protection filter', () => {
  it('omits the key entirely for no selection', () => {
    expect(apiProtection('any')).toBeUndefined();
    expect(apiProtection(undefined)).toBeUndefined();
    expect(apiProtection('all')).toBeUndefined();  // hand-edited URL
    expect(apiProtection('')).toBeUndefined();     // never emit ?protection=
  });

  it('passes the two real values through', () => {
    expect(apiProtection('soft')).toBe('soft');
    expect(apiProtection('hard')).toBe('hard');
  });

  it('does not use `all` anywhere in its vocabulary', () => {
    // buildParams' own sentinel. Two toggle states building byte-identical
    // params is the bug that stopped ScopeWindowsTable ever refetching.
    expect(PROTECTION_FILTER_NONE).toBe('any');
  });

  it('refetches when the filter changes between its two real values', async () => {
    // Render, switch soft -> hard, assert a SECOND request went out carrying
    // protection=hard. Mount-only is not enough: the bug this guards against
    // is two states collapsing to one request.
  });

  it('has no custom-field column whose field collides with protection_level', () => {
    // The `cf_` namespacing rule — BookingList was namespaced on 2026-08-04
    // precisely because a tenant custom field keyed like a static column
    // silently hid the real one via a persisted visibility entry.
  });
});
```

- [ ] **Step 2: Run to verify they fail, then implement**

Add `apiProtection` beside `apiAgreementGap`, following its docstring style and its three-state contract. Add a `protection_level` column to `bookingColumns` rendering `PROTECTION_LABELS[row.protection_level]` as a `Chip`, `sortable: true` — and update the sortable-fields comment at line ~153, which currently lists three fields and explains why the rest cannot be sorted; `protection_level` is the first addition to that list, so say why it qualifies. Add `'protection'` to `filterKeys` and map it in the params builder. Add a `Select` to the filter bar using `PROTECTION_FILTER_NONE`.

Add `"protection_level"` to `bookings.sortable` in `frontend/src/constants/sortWhitelists.json` — **the backend whitelist and this file must agree**, or a sort the UI offers is a 422.

- [ ] **Step 3: Run to verify they pass, then commit**

```bash
cd frontend && npx vitest run src/pages/bookings
git add frontend/src
git commit -m "feat(b4): protection column, filter and sort on the bookings list"
```

---

## Task 12: The verdict and the detail header

**Files:**
- Modify: `frontend/src/components/bookings/ContentionVerdict.tsx`, `frontend/src/pages/bookings/BookingDetail.tsx`
- Test: `frontend/src/components/bookings/__tests__/ContentionVerdict.test.tsx` (existing — extend)

**Interfaces:**
- Consumes: `outcome: 'protected'` and its composed `reason` from the server.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Add to the existing file, inside a new `describe('B4 — the protected outcome')`:

```tsx
it("renders the server's composed reason verbatim", () => {
  // outcome 'protected', reason "both projects have the same priority rank;
  // the protected booking holds". The component RENDERS that string — it does
  // not compose one. Composing here is the B2 regex mistake in a different
  // costume: two evaluators of one rule that disagree on real inputs.
});

it('names the winner for a protected outcome', () => {
  // 'protected' is the FIRST outcome other than 'ranked' that has a winner.
  // The existing `composedVerdict` guard keys on `outcome === 'ranked'`, so
  // it will silently skip this one until it is widened.
});

it('still names nobody for the three no-winner outcomes', () => {});
```

`ContentionVerdict.tsx:161` currently reads `contention.outcome === 'ranked' && Boolean(winnerName && loserName)`. That is the line that must change, and the second test is the one that catches it.

- [ ] **Step 2: Run to verify they fail, then implement**

Widen the winner-naming condition to `(contention.outcome === 'ranked' || contention.outcome === 'protected')`, keeping the `winnerName && loserName` guard. Do not add a client-side reason.

In `BookingDetail.tsx`, render a `Chip` with `PROTECTION_LABELS[...]` beside the status, with a tooltip carrying the helper text from Task 9.

- [ ] **Step 3: Run the whole bookings suite, then commit**

```bash
cd frontend && npx vitest run src/components/bookings src/pages/bookings
git add frontend/src
git commit -m "feat(b4): render the protected verdict and the level on booking detail"
```

---

## Task 13: Calendar and Gantt

**Files:**
- Modify: `frontend/src/pages/bookings/BookingCalendar.tsx:52-53`, `frontend/src/components/BookingScheduleGantt.tsx:296-340`
- Test: `frontend/src/pages/bookings/__tests__/bookingCalendarProtection.test.tsx`

**Interfaces:**
- Consumes: `protection_level` on the booking rows both already fetch.
- Produces: nothing.

- [ ] **Step 1: Write the failing test**

```tsx
/**
 * Both components spend colour on STATUS_COLORS already, and a border alone is
 * not accessible. The marker is paired with the words "Protected (hard)
 * reservation" — which is also the only thing jsdom can assert on, since
 * neither component's geometry renders there. jsdom could not render A3's
 * DataGrid gap column at all (a scratch render gave 1 row, 3 cells, 0 icons),
 * so assert on TEXT, never on a style.
 */
const HARD_BOOKING = {
  id: 1,
  environment_id: 10,
  environment_name: 'SIT',
  project_name: 'Release 24.4',
  start_date: '2026-09-01T09:00:00Z',
  end_date: '2026-09-05T17:00:00Z',
  status: 'approved',
  protection_level: 'hard',
} as never;

const SOFT_BOOKING = { ...HARD_BOOKING, id: 2, protection_level: 'soft' } as never;

it('marks a protected booking with text, not colour alone', async () => {
  vi.mocked(bookingService.listBookings).mockResolvedValue({
    items: [HARD_BOOKING],
    total: 1,
  } as never);
  renderCalendar();

  expect(
    await screen.findByTitle(/protected \(hard\) reservation/i),
  ).toBeInTheDocument();
});

it('leaves a soft booking unmarked', async () => {
  vi.mocked(bookingService.listBookings).mockResolvedValue({
    items: [SOFT_BOOKING],
    total: 1,
  } as never);
  renderCalendar();

  await screen.findByText(/release 24\.4/i);
  expect(screen.queryByTitle(/protected \(hard\) reservation/i)).toBeNull();
});
```

Copy the mock block and `renderCalendar()` from `bookingCalendarOwnFetch.test.tsx`, which already builds a store with `configureStore({ reducer: { auth: authReducer, ... } })` for this page. Write the matching pair for `BookingScheduleGantt` in the same file, rendering the component directly with a `bookings` prop rather than through a page.

If FullCalendar renders nothing useful in jsdom — check `bookingCalendarOwnFetch.test.tsx` to see what it manages to assert — then assert on the **event objects** the page builds instead: export the mapping function and test that a hard booking gets `classNames: ['booking-protected']` and the title text. A test that silently asserts nothing is worse than one that admits it tests the mapping.

- [ ] **Step 2: Run to verify it fails, then implement**

`BookingCalendar.tsx`: keep `backgroundColor` as `STATUS_COLORS[...]`; for a hard booking set `borderColor` to a contrasting accent and add `classNames: ['booking-protected']`, with a small CSS rule giving a 2px dashed inset outline. Add "Protected (hard) reservation" to the event's title/tooltip.

`BookingScheduleGantt.tsx`: add `outline` + `outlineOffset` to the bar's `sx` for hard bookings, and a third `<Typography variant="caption">` line to the existing `<Tooltip>` title carrying the same words. Add the marker to the legend at line ~409.

- [ ] **Step 3: Run to verify it passes, then commit**

```bash
cd frontend && npx vitest run src/pages/bookings src/components
git add frontend/src
git commit -m "feat(b4): protected bookings marked on the calendar and the schedule Gantt"
```

---

## Task 14: Documentation

**Files:**
- Modify: `docs/admin-guide.md`, `docs/user-guide.md`, `docs/phases/phase-7.md`, `docs/pagination.md`, `CLAUDE.md`

**Interfaces:** none.

- [ ] **Step 1: Admin guide**

A "Protection levels" section under the booking-type configuration: what the two levels mean, that the default is inherited from the booking type and only Admin/Release Manager can change it per booking, and the duration preset. State plainly:

> A protected reservation is **advice, not a lock**. Anyone can still book over it. What "protected" changes is who is named the winner when two bookings clash and project priority cannot separate them.

And the degradation, which will otherwise read as the feature breaking:

> If every booking type is set to Protected, the level stops discriminating and contention verdicts return to naming no winner — exactly as they did before protection levels existed. There is no quota on protected bookings; the role gate is the whole control.

- [ ] **Step 2: User guide**

Under bookings: the two controls and how they differ, in the same words as the form's helper text. Say explicitly that exclusive use and protection are different questions, and that neither prevents someone else booking the environment through the multi-environment request path.

- [ ] **Step 3: `docs/phases/phase-7.md`**

Tick B4, add its spec link, and add a "What B4 established" section following the shape of the A4 and B2 sections: rank stays primary; the level is on the request, not the booking, and why A2's atomicity depends on that; the unknown-level rule; the unchanged-value carve-out; `OUTCOME_PROTECTED` being the first non-`ranked` outcome with a winner; and the §2.12 "preemptible" deviation.

- [ ] **Step 4: `docs/pagination.md`**

Add `protection_level` to the bookings sortable list, and note that it is deliberately **not** a member of the permanently-unsortable set that `agreement_gap` heads — with the one-line reason (stored column vs post-query computation).

- [ ] **Step 5: `CLAUDE.md`**

A B4 block after B2's, in the established voice: the promise and its guard test, the precedence rule, the two-axes distinction from `exclusive_use_requested` including the standing legacy-vs-modern asymmetry left unfixed, the DST duration rule, and the zero-length-booking defect this branch fixed. Add the two-axes point to Common Pitfalls.

- [ ] **Step 6: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs(b4): protection levels in the guides, phase-7, pagination and the pitfalls"
```

---

## Task 15: Whole-branch verification

**Files:** none — this task fixes what it finds.

**Interfaces:** none.

- [ ] **Step 1: Both engines, whole suite**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test PYTHONPATH=. uv run pytest -q
cd ../frontend && npx vitest run && npm run lint && npm run build
```
Expected: green throughout. Record the counts.

- [ ] **Step 2: Migration from a clean database**

Build a scratch database, `alembic upgrade head` from empty, and confirm the three columns exist with the right types and defaults. **Do not** use `alembic downgrade -1` on the dev database.

- [ ] **Step 3: Mutation pass over the whole B4 file set**

For each rule below: break it, run the **whole** suite, confirm a named test fails, restore. Not the file you expect — the whole set. B2's carve-out was guarded by a test in a different file than its plan named.

1. Protection consulted in the `ranked` branch.
2. `_protection_breaks_tie` firing on equality.
3. The `missing` sentinel's last element set to `"soft"`.
4. `assert_may_set_protection`'s `submitted == current` clause removed.
5. `assert_may_set_protection`'s role check removed.
6. `?protection=` applied in Python after the query instead of in SQL.
7. `protection_level` dropped from one `EnvBookingSummary` construction site.
8. `addDuration`'s calendar-day branch replaced with minute arithmetic.

- [ ] **Step 4: Open the page**

Every sub-project since A3 has found defects here that no test could see — three on B2 alone, all of them presentation of a refusal or a choice. Run the app (`docker-compose up -d`, backend `uvicorn`, frontend `npm run dev`) and walk:

1. Set a booking type to Protected with a 240-minute duration in the admin panel. Reload and confirm both persisted.
2. Create a booking on that type as a Developer — confirm the end fills to +4h, the level shows Preemptible/Protected read-only, and the save succeeds. **This is the carve-out; if it 403s, the primary journey is broken.**
3. As an Admin, override a booking to Protected. Confirm the list column, the filter (switch between both values and confirm the row set changes — not just that the control moves), and the sort.
4. Make two conflicting bookings on equal-ranked projects, one hard. Confirm the Conflicts panel names the protected winner and gives the composed reason.
5. Confirm the calendar and Gantt markers, and that the tooltip text is there.
6. Edit a half-day booking through the standard-fields dialog and confirm its times survive.
7. Check the browser console for errors on every page touched.

- [ ] **Step 5: Fix what you found, commit, and report**

Commit fixes separately (`fix(b4): ...`) so the browser-only defects are visible as their own class in the log. Then report: test counts on both engines, which mutations were caught by which test, and every defect found by opening the page.

```bash
git add -A backend frontend docs CLAUDE.md
git commit -m "test(b4): whole-branch verification — dual engine, mutation pass, browser pass"
```

---

## Self-Review

**Spec coverage** — every section maps to a task: data model → 1; verdict extension incl. the unknown-level rule → 4; setting the level (create, update, carve-out) → 2, 3; duration by rule → 9; the `datetime-local` defect → 10; API (`?protection=`, sorts, response fields, booking-type schemas) → 5, 6, 2; UI 1–6 → 9, 11, 12, 13, 8; testing (the promise, inertness, the named rules, dual engine) → 7, 4, 15; migration → 1; risks → 14 (the all-hard degradation is documented) and 15.

**Type consistency** — `assert_may_set_protection(user, *, submitted, current)` is defined in Task 2 and consumed unchanged in Task 3. `_ranks_for`'s 4-tuple is produced in Task 4 and consumed only there. `addDuration(start, minutes)` is defined in Task 9 and used in Task 9. `apiProtection` is defined and used in Task 11. `PROTECTION_FILTER_NONE` is defined in Task 8 and used in Task 11.

**Placeholder scan** — every test body is written out. The frontend tests in Tasks 9, 10 and 13 name the sibling file whose mock block and render helper to copy (`bookingFormGroups.test.tsx`, `bookingCalendarOwnFetch.test.tsx`) and say which parts are contracts to assert rather than exact prop names, because those vary between components. Two tests in Task 8 and the five in Task 11 are given in full. The only genuinely open instruction is Task 6's "check how the update handler applies its fields" — that branch cannot be resolved without reading the handler, and the plan says what to do in either case.

**Fixtures the backend tasks assume** — `hard_booking_type`, `developer_headers`, `soft_request`, `soft_bookings_25`, `hard_bookings_3`, `soft_booking`, `hard_booking`. None exists yet. Task 2 introduces the first two, Task 3 the third, Task 5 the next two, Task 7 the last two; each task's Step 1 says to build them with `backend/tests/factories.py` helpers. Check `conftest.py` for the repo's existing `tenant` / `user` / `environment` / `booking_type` / `lifecycle_template` fixture names before writing any of them, and never fabricate a foreign key.
