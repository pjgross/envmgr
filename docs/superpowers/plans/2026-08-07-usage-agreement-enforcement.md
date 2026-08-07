# Usage Agreement Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Warn — never block — when a booking's project has no usage agreement covering the environment and dates, and let that warning be acknowledged.

**Architecture:** The warning is **computed**, never stored; only the acknowledgement is persisted, mirroring the conflicts mechanism exactly. The coverage test is written as a **SQL predicate first**, so the same expression serves the per-booking answer, the response field and the bounded list filter without three implementations that can disagree.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 (backend); React 18, TypeScript, MUI, Redux Toolkit (frontend). Tests: pytest (SQLite + PostgreSQL), vitest.

**Spec:** [docs/superpowers/specs/2026-08-07-usage-agreement-enforcement-design.md](../specs/2026-08-07-usage-agreement-enforcement-design.md)

## Global Constraints

- **A3 WARNS, IT NEVER BLOCKS.** No booking is refused. `A1`'s `test_an_agreement_changes_no_booking_behaviour` must stay green — it exists to detect this sub-project overstepping. **If it fails, you have made A3 block.**
- **A request with no `project_id` is never checked**, whatever the agreements say.
- **"Live agreement" is NOT `deleted_at IS NULL`.** The predicate must filter the agreement, **its project AND its environment**, exactly as `project_service._agreement_query` does. `delete_project` cascades to agreements; **`delete_environment` does not**, so a soft-deleted environment leaves rows a naive query would honour.
- **`usage_agreement` is not modified.** A1 shipped it whole so A3 owns only the check.
- `current_user.active_tenant_id`, never `.tenant_id`. Cross-tenant ids are **404, never 403**, on create and on update.
- **Every filter runs in SQL.** `GET /bookings` is bounded; a Python-side filter windows the page before filtering.
- Services never call `db.commit()`; use `db.flush()`.
- Migrations are hand-written, never `--autogenerate`. `tests/test_migration_schema_drift.py` compares only column **name sets**.
- Frontend thunks `rejectWithValue(formatApiError(err, ...))`; components read `result.payload`. A component calling a service **directly** must call `formatApiError` itself in its own catch. Tests reject with an **AxiosError shape**.
- A new list filter spells "no selection" `any`, never `all` — `buildParams` drops `all`, so both states build identical params and the grid never refetches.
- **Frontend tests must re-render, not only mount**, and must not mock the component on the other side of a seam they are verifying. Both shapes hid real defects on A2.
- Backend from `backend/` via `uv run`; frontend from `frontend/`.
- **Do not run the full test suite in a task** — run the focused tests named. The controller runs full suites.
- PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q -p no:logging`

## File Structure

**Backend — create**
- `app/services/agreement_gap_service.py` — the SQL predicate and everything derived from it
- `app/db/models/usage_agreement_ack.py`
- `app/db/migrations/versions/20260808_1200_agreementack_add_usage_agreement_ack.py`
- `tests/integration/test_agreement_gap.py`, `tests/integration/test_agreement_gap_ack.py`, `tests/integration/test_agreement_gap_filter.py`

**Backend — modify**
- `app/api/v1/schemas/booking_lifecycle.py` — Task 1
- `app/api/v1/schemas/booking.py`, `app/api/v1/schemas/booking_request.py`
- `app/api/v1/bookings.py`, `app/api/v1/booking_requests.py`
- `app/services/booking_service.py` (the list filter only)
- `app/db/models/__init__.py`, `app/main.py`, `tests/factories.py`, `tests/test_pagination.py`

**Frontend — create**
- `src/types/agreementGap.ts`, `src/services/agreementGapService.ts`
- `src/components/bookings/AgreementGapPanel.tsx`
- matching `__tests__/` files

**Frontend — modify**
- `src/components/bookings/EditStandardFieldsDialog.tsx` — Task 1
- `src/pages/bookings/BookingForm.tsx`, `BookingDetail.tsx`, `BookingList.tsx`
- `src/pages/admin/ProjectDetail.tsx`
- `src/types/booking.ts`, `src/types/bookingRequest.ts`

---

### Task 1: The prerequisite — make a booking's project correctable

**Files:**
- Modify: `backend/app/api/v1/schemas/booking_lifecycle.py`, `frontend/src/components/bookings/EditStandardFieldsDialog.tsx`
- Test: `backend/tests/integration/test_project_links_bookings.py`, `frontend/src/components/bookings/__tests__/EditStandardFieldsDialog.test.tsx`

**Interfaces:**
- Produces: `project_id` accepted by `PATCH /booking-requests/{id}/standard-fields` **and** offered by the edit dialog.

**Why this is Task 1 and not a nicety:** `ENTITY_FIELD_SPECS["booking"]["valid"]` omits `project_id` and so does the dialog's `fieldMap`, so a booking's project is **create-only**. Warning on a field nobody can correct is the failure mode this project has fixed repeatedly. Nothing else in A3 is safe to build until this lands.

- [ ] **Step 1: Write the failing tests**

Backend — append to `backend/tests/integration/test_project_links_bookings.py`:

```python
@pytest.mark.asyncio
async def test_a_bookings_project_can_be_corrected_after_creation(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    """A3 warns on project_id, so a mislinked booking must be fixable.

    Before this, ENTITY_FIELD_SPECS["booking"]["valid"] omitted project_id, so
    the only remedy was to delete the booking and recreate it.
    """
    wrong = await ensure_project(db_session, test_tenant.id, name="Wrong Project")
    right = await ensure_project(db_session, test_tenant.id, name="Right Project")
    env = await ensure_environment(db_session, test_tenant.id)
    await db_session.commit()

    rid = (await client.post(
        "/api/v1/booking-requests",
        json=_payload(test_booking_type.id, env.id, project_id=wrong.id),
        headers=auth_headers,
    )).json()["request"]["id"]

    fixed = await client.patch(
        f"/api/v1/booking-requests/{rid}/standard-fields",
        json={"project_id": right.id},
        headers=auth_headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["project_id"] == right.id
    assert fixed.json()["project_name_link"] == "Right Project"

    # And it persisted, not merely echoed.
    again = await client.get(f"/api/v1/booking-requests/{rid}", headers=auth_headers)
    assert again.json()["project_id"] == right.id
```

Check `_payload`'s real signature at the top of that file and match it — `POST /booking-requests` returns `{request, detected_conflicts}`, not the bare body.

Frontend — add to `frontend/src/components/bookings/__tests__/EditStandardFieldsDialog.test.tsx` a test that the dialog renders a Project field and sends `project_id` on save. Give the fixture a project id that does **not** appear in any other mock in the file, so the assertion cannot pass by coincidence — that shape masked three tests on A2.

- [ ] **Step 2: Run them to verify they fail**

Backend: `cd backend && uv run pytest tests/integration/test_project_links_bookings.py -q -p no:logging`
Expected: FAIL — `400 Unknown fields: project_id`, or the value is silently dropped.

Frontend: `cd frontend && npx vitest run src/components/bookings`
Expected: FAIL — no Project field.

- [ ] **Step 3: Add `project_id` to the booking field spec**

In `backend/app/api/v1/schemas/booking_lifecycle.py`, in `ENTITY_FIELD_SPECS["booking"]["valid"]`, add `"project_id"`. **Do not add it to `mandatory`** — a booking without a project is legitimate and is exactly what A3 declines to check.

Check whether `update_standard_fields` validates values against a lifecycle template's `field_permissions`; if it does, confirm `project_id` behaves like the other optional standard fields rather than needing a per-state entry.

- [ ] **Step 4: Add it to the edit dialog**

In `frontend/src/components/bookings/EditStandardFieldsDialog.tsx`, add `project_id` to the `fieldMap` and render a picker sourced from **`useAllProjects()`** (`is_active: true`, `useSharedList`-backed) — never `state.project.projects`, which is a page-scoped paged slice.

**Carve out the stored value the way `ReleaseForm` does:** if the booking's current `project_id` is not in the active list (the project was archived), render an extra option for it so the form does not silently clear the link. A1 shipped that carve-out on the backend; the form must not undo it.

- [ ] **Step 5: Run both, then commit**

Run the backend file on **both** engines and `npx vitest run src/components/bookings && npx tsc --noEmit && npm run lint`.

```bash
git add backend/app/api/v1/schemas/booking_lifecycle.py \
        backend/tests/integration/test_project_links_bookings.py \
        frontend/src/components/bookings/
git commit -m "feat(agreements): let a booking's project be corrected after creation"
```

---

### Task 2: The gap predicate

**Files:**
- Create: `backend/app/services/agreement_gap_service.py`, `backend/tests/integration/test_agreement_gap.py`

**Interfaces:**
- Consumes: `UsageAgreement`, `Project`, `Environment`.
- Produces:
  - `covered_exists_clause(tenant_id)` — a correlated `EXISTS` usable in any query selecting from `Booking`
  - `describe_gap(db, booking, tenant_id) -> str | None` — the human message, or `None` when there is no gap
  - `gaps_for_bookings(db, bookings, tenant_id) -> dict[int, str]` — batch, `booking_id -> message`

**This is the heart of A3. Write the SQL first.**

- [ ] **Step 1: Write the failing test**

Create `backend/tests/integration/test_agreement_gap.py` covering, each as its own test:

- **a request with no `project_id` is never in gap**, even with zero agreements anywhere;
- an agreement with **both bounds null** covers any dates;
- an agreement with only `starts_at` covers anything after it; only `ends_at`, anything before;
- a booking **inside** the window is covered; one **outside** is in gap, and the message names the window;
- **no agreement at all** for that environment → gap, message names the **environment**;
- **overlapping agreements where one covers and one does not → NOT in gap** (A1 made overlaps legal; coverage is "any single agreement covers it");
- **an agreement whose ENVIRONMENT was soft-deleted does not count as coverage.** Seed it by soft-deleting the environment **directly**, *not* via `delete_project` — that cascade would hide the row a second way and mask the predicate under test. This exact masking shape appeared three times on A2;
- **an agreement whose PROJECT was soft-deleted does not count** either;
- **an agreement belonging to another tenant does not count** — seed a malformed row directly, as `test_usage_agreements_api.py` does in its three defence-in-depth tests.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/integration/test_agreement_gap.py -q -p no:logging`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.agreement_gap_service'`

- [ ] **Step 3: Write the predicate**

Create `backend/app/services/agreement_gap_service.py`:

```python
"""Is a booking covered by one of its project's usage agreements?

A3 WARNS; it never blocks. Nothing here refuses a booking — the caller
surfaces what this returns and carries on.

The coverage test is written as a SQL EXISTS first, and everything else is
derived from it. `GET /bookings` is bounded, so the filter must push down: a
Python-side filter would window the page BEFORE filtering and return the wrong
rows. Writing the Python form first and discovering later that it cannot be
pushed down is how `dependency-alerts` became permanently unbounded.
"""
from typing import Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.db.models.booking_request import BookingRequest
from app.db.models.environment import Environment
from app.db.models.project import Project, UsageAgreement


def covered_exists_clause(tenant_id: int):
    """EXISTS(a live agreement covering this booking's project, environment
    and dates).

    Correlates against `Booking` and `BookingRequest`, so any query selecting
    from Booking joined to its request can use it directly.

    "LIVE" IS NOT `deleted_at IS NULL` ON THE AGREEMENT ALONE. The project and
    the environment must both be live too, exactly as
    project_service._agreement_query requires. `delete_project` cascades a
    soft delete to its agreements; **`delete_environment` does not**, so a
    soft-deleted environment leaves agreement rows with a null `deleted_at`
    pointing at it — invisible to A1's list endpoints and fully visible to a
    naive query. Filtering only the agreement would honour agreements for dead
    environments.

    Window semantics: a null bound means NO bound, not "unknown". An agreement
    covers the booking when it starts no later than the booking starts and
    ends no earlier than the booking ends.
    """
    return (
        select(UsageAgreement.id)
        .join(
            Project,
            and_(
                Project.id == UsageAgreement.project_id,
                Project.tenant_id == tenant_id,
                Project.deleted_at.is_(None),
            ),
        )
        .join(
            Environment,
            and_(
                Environment.id == UsageAgreement.environment_id,
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            ),
        )
        .where(
            UsageAgreement.tenant_id == tenant_id,
            UsageAgreement.deleted_at.is_(None),
            UsageAgreement.project_id == BookingRequest.project_id,
            UsageAgreement.environment_id == Booking.environment_id,
            or_(
                UsageAgreement.starts_at.is_(None),
                UsageAgreement.starts_at <= Booking.start_date,
            ),
            or_(
                UsageAgreement.ends_at.is_(None),
                UsageAgreement.ends_at >= Booking.end_date,
            ),
        )
        .correlate(Booking, BookingRequest)
        .exists()
    )


def gap_clause(tenant_id: int):
    """The filter form: this booking's request names a project AND no live
    agreement covers it.

    The `project_id IS NOT NULL` half is load-bearing, not defensive — a
    booking with no project is never in gap, and most existing bookings have
    none.
    """
    return and_(
        BookingRequest.project_id.is_not(None),
        ~covered_exists_clause(tenant_id),
    )
```

Then `describe_gap` and `gaps_for_bookings`. **Both must derive their answer from `gap_clause`**, not from a re-implemented Python comparison — one expression, three consumers. `gaps_for_bookings` runs one query over the given booking ids and returns messages only for those in gap.

The message distinguishes the two cases by asking a second, cheap question: does the project have **any** live agreement for this environment?
- none → `f"{project.name} has no usage agreement for {environment.name}"`
- some → `f"{project.name}'s booking falls outside its agreed window for {environment.name}"`, naming the nearest window.

- [ ] **Step 4: Run the tests, both engines, then commit**

```bash
git add backend/app/services/agreement_gap_service.py \
        backend/tests/integration/test_agreement_gap.py
git commit -m "feat(agreements): SQL predicate for usage-agreement coverage"
```

---

### Task 3: The acknowledgement

**Files:**
- Create: `backend/app/db/models/usage_agreement_ack.py`, the migration, `backend/tests/integration/test_agreement_gap_ack.py`
- Modify: `backend/app/db/models/__init__.py`, `backend/tests/factories.py`, `backend/app/services/agreement_gap_service.py`, `backend/app/api/v1/bookings.py`

**Interfaces:**
- Produces: `UsageAgreementAck(tenant_id, booking_id, notes, acknowledged_by, acknowledged_at)`; `upsert_ack(db, booking_id, notes, current_user, tenant_id) -> UsageAgreementAck`; `get_ack(db, booking_id, tenant_id) -> UsageAgreementAck | None`; `has_unacknowledged_agreement_gap(db, booking_id, tenant_id) -> bool`. Route `PUT /bookings/{id}/agreement-gap/ack`.

- [ ] **Step 1: Write the failing test**

`backend/tests/integration/test_agreement_gap_ack.py` must cover:

- acknowledging a booking in gap returns 200 and records **who and when**;
- `has_unacknowledged_agreement_gap` is true before and false after;
- **a booking with no gap is never unacknowledged**, ack or no ack;
- **adding the missing agreement clears the gap with no ack and no other action** — the property the computed-not-stored design exists to give. Assert it directly;
- acknowledging another tenant's booking is **404**;
- re-acknowledging **updates** the existing row rather than creating a second (it is an upsert keyed on `booking_id`).

- [ ] **Step 2: Run it to verify it fails, then write the model**

Create `backend/app/db/models/usage_agreement_ack.py`, modelled on `app/db/models/booking_conflict_ack.py`:

```python
"""Acknowledgement that a booking's usage-agreement gap has been seen.

ONLY THE ACKNOWLEDGEMENT IS STORED. The gap itself is computed by
agreement_gap_service, so adding the missing agreement makes the warning
disappear with nothing to invalidate — no stored flag can drift from the
usage_agreement table it summarises.

Keyed on booking_id alone: unlike a conflict, which is pairwise, a gap is a
property of one booking.

ACCEPTED WRINKLE: a booking's dates are editable, so acknowledging "outside
the agreed window" and then moving the dates leaves a stale ack suppressing a
warning it was never given for. Conflicts have the same property and accept
it; building ack-invalidation would add a state machine nobody has asked for.
"""
```

Fields: `tenant_id` FK, `booking_id` FK (indexed), `notes` Text nullable, `acknowledged_by` FK `user.id`, `acknowledged_at` tz-aware.

- [ ] **Step 3: Write the migration**

Confirm `uv run alembic current` prints `envgroups`. Revision `agreementack`, `down_revision = 'envgroups'`. One table plus its indexes — including `ix_usage_agreement_ack_id`, which `Base` implies and which the `usergroups` migration had to be corrected for omitting.

**Verify by hand against the models** — types, timezone-awareness, server defaults, nullability, index names. `test_migration_schema_drift.py` compares only column **name sets**; four real drifts passed it on B3a.

**Do not run `alembic downgrade -1` against the dev database.** Use a scratch database.

- [ ] **Step 4: Add the service functions and the endpoint**

`upsert_ack`, `get_ack`, `has_unacknowledged_agreement_gap` in `agreement_gap_service` — named to match the response field it feeds, so a reader does not have to check whether they are the same question. It returns false when there is **no gap**, regardless of acks — mirroring `conflict_service.has_unacknowledged_conflicts`, which returns `False` early when `not conflicts`.

Route in `backend/app/api/v1/bookings.py`:

```python
@router.put("/{booking_id}/agreement-gap/ack", response_model=AgreementGapAckRead)
async def ack_agreement_gap(
    booking_id: int,
    data: AgreementGapAckUpsert,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    ack = await agreement_gap_service.upsert_ack(
        db, booking_id, notes=data.notes,
        current_user=current_user, tenant_id=current_user.active_tenant_id,
    )
    return AgreementGapAckRead.model_validate(ack)
```

- [ ] **Step 5: Run both engines, then commit**

```bash
git add backend/app/db/models/usage_agreement_ack.py backend/app/db/models/__init__.py \
        backend/app/db/migrations/versions/20260808_1200_agreementack_add_usage_agreement_ack.py \
        backend/app/services/agreement_gap_service.py backend/app/api/v1/ \
        backend/tests/factories.py backend/tests/integration/test_agreement_gap_ack.py
git commit -m "feat(agreements): acknowledge a usage-agreement gap"
```

---

### Task 4: Responses and the list filter

**Files:**
- Modify: `backend/app/api/v1/schemas/booking.py`, `backend/app/api/v1/booking_requests.py`, `backend/app/api/v1/bookings.py`, `backend/app/services/booking_service.py`
- Create: `backend/tests/integration/test_agreement_gap_filter.py`

**Interfaces:**
- Produces: `agreement_gaps` on the create envelope; `agreement_gap: str | None` and `has_unacknowledged_agreement_gap: bool` on booking responses; `?agreement_gap=` on `GET /bookings`.

- [ ] **Step 1: Write the failing test**

`test_agreement_gap_filter.py` must cover:

- `POST /booking-requests` returns `agreement_gaps` beside `detected_conflicts`, keyed by booking id, **naming the environment**;
- a booking response carries `agreement_gap` and `has_unacknowledged_agreement_gap`;
- **`GET /bookings?agreement_gap=true` returns only bookings in gap, and `X-Total-Count` matches** — the header proves it filtered in SQL rather than in Python after the page;
- `?agreement_gap=false` returns the complement;
- **omitting the parameter returns everything** — and the "no selection" value must not be spelled `all`;
- **the filter and the per-booking answer agree** over a set containing covered, uncovered, out-of-window and no-project bookings. Assert them **against each other**, not separately: A1 shipped a count and a list, written three tasks apart, that disagreed two ways with zero coverage.

- [ ] **Step 2: Run it, then implement**

Add the fields to `BookingResponse` and `EnvBookingSummary`. **Enumerate every construction site by grepping for the type**, not by reading the routes you notice — A2's implementer scoped its grep to the files a brief named and missed two, leaving the API self-contradictory about the same booking. There are six.

Make any new helper parameter **required-positional, not defaulted**: Pydantic silently defaults a missing non-column attribute rather than raising, and A1 shipped four of five call sites rendering `null` because of exactly that.

Add `agreement_gap: Optional[bool] = Query(None)` to `GET /bookings`, applied with `gap_clause(tenant_id)` **in SQL**.

- [ ] **Step 3: Add the pagination row, run both engines, commit**

Because this touches shared response builders, also run `tests/test_booking_requests_api.py`, `tests/integration/test_group_booking_create.py` and `tests/test_pagination.py`.

```bash
git add backend/app/api/v1/ backend/app/services/booking_service.py \
        backend/tests/integration/test_agreement_gap_filter.py backend/tests/test_pagination.py
git commit -m "feat(agreements): surface gaps on responses and filter the bookings list"
```

---

### Task 5: Frontend types, service and slice wiring

**Files:**
- Create: `frontend/src/types/agreementGap.ts`, `frontend/src/services/agreementGapService.ts`, and a test
- Modify: `frontend/src/types/booking.ts`, `frontend/src/types/bookingRequest.ts`

**Interfaces:**
- Produces: `AgreementGapAckRead`; `agreementGapService.ackGap(bookingId, notes)`; `agreement_gap: string | null` and `has_unacknowledged_agreement_gap: boolean` on the booking response types; `agreement_gaps: Record<number, string>` on the create response type.

- [ ] **Step 1: Write the failing test, then implement**

Follow `frontend/src/services/environmentGroupService.ts` for shape. **No slice thunk** — the ack is called directly from the component, matching `bookingService.transitionState`. That means **the component must call `formatApiError` itself in its own catch**; there is no `miniSerializeError` boundary and no lint rule enforcing it.

Adding required fields to existing response types will break fixtures' typechecking. **Add explicit `null`/`false` rather than making the fields optional** — an optional field would make the type lie about the wire contract. Report how many you touched.

- [ ] **Step 2: Run, typecheck, commit**

`npx vitest run src/services src/store && npx tsc --noEmit`

```bash
git add frontend/src/types/ frontend/src/services/agreementGapService.ts frontend/src/services/__tests__/
git commit -m "feat(agreements): frontend types and gap-ack service"
```

---

### Task 6: The gap on the booking form and booking detail

**Files:**
- Create: `frontend/src/components/bookings/AgreementGapPanel.tsx` and its test
- Modify: `frontend/src/pages/bookings/BookingForm.tsx`, `frontend/src/pages/bookings/BookingDetail.tsx`

- [ ] **Step 1: Write the failing tests**

- the booking form shows returned `agreement_gaps` after a successful create, **naming each environment**, without blocking anything;
- `AgreementGapPanel` renders the gap message, an Acknowledge control, and — once acknowledged — **who and when**;
- a failed ack renders the **server's** message via `formatApiError`, not a raw error or a status line. Reject with an **AxiosError shape**;
- **an acknowledged gap still shows the gap**, just no longer as unacknowledged — acknowledging is not resolving;
- a booking with no gap renders no panel at all.

**Mount the real panel inside `BookingDetail` for at least one test.** On A2, both ends of a seam were tested and the join was not: deleting the wiring left 43 tests green while the feature regressed entirely. And **re-render at least once** — two A2 defects needed a second render to surface.

- [ ] **Step 2: Implement, run, commit**

Render an **error state, not an eternal skeleton** — check which calls set state and whether any sets a loading flag before keying a skeleton on one.

```bash
git add frontend/src/components/bookings/ frontend/src/pages/bookings/
git commit -m "feat(agreements): show and acknowledge usage-agreement gaps"
```

---

### Task 7: The list filter, project detail, docs and the browser pass

**Files:**
- Modify: `frontend/src/pages/bookings/BookingList.tsx`, `frontend/src/pages/admin/ProjectDetail.tsx`, `docs/phases/phase-7.md`, `docs/pagination.md`, `docs/admin-guide.md`, `docs/user-guide.md`

- [ ] **Step 1: `BookingList`**

A gap chip on each row and an `agreement_gap` filter. Its "no selection" value is **`any`, never `all`** — `buildParams` drops `all`, so both states build byte-identical params and the grid never refetches. That defect has shipped here once.

The chip column is `sortable: false` — the gap is computed, not a sortable column.

- [ ] **Step 2: Project detail**

Beside the agreements table, a count of that project's bookings currently in gap, linking to `/bookings/list?project_id=<id>&agreement_gap=true`. **Verify the filter parameters you link to actually exist** — A1 shipped a count linking to a filter that did not exist, because FastAPI drops unknown query params silently and a test plus the admin guide both asserted it as correct.

- [ ] **Step 3: The four documents**

- **`docs/phases/phase-7.md`** — tick A3; add "What A3 established"; and **correct the A3 line itself**, which assigns it "the cooperation rules of §2.12" — that content is priority-ordered contention and escalation, which is A4's line almost word for word.
- **`docs/pagination.md`** — re-run the file's own grep and record the **delta**, not a re-baseline. Add the `agreement_gap` filter to `GET /bookings`.
- **`docs/admin-guide.md`** — that agreements now produce a warning, that nothing is blocked, and where to see the gaps.
- **`docs/user-guide.md`** — what the warning means and that acknowledging is not resolving.

- [ ] **Step 4: The browser pass**

Ten defects across the last four sub-projects were found only by opening the page.

1. Book an environment the project has an agreement for — **no warning**.
2. Book one it does not — warning naming the environment, **booking still created**.
3. Acknowledge it; confirm who and when, and that the gap still shows.
4. **Add the missing agreement; confirm the warning disappears with no other action.**
5. Book with **no project** — no warning at all.
6. Filter `BookingList` by gap; confirm the count and that the filter survives a reload.
7. Correct a booking's project from the edit dialog (Task 1) and confirm the warning re-evaluates.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ docs/
git commit -m "feat(agreements): gap filter, project rollup, and document A3"
```

---

## Final verification

- [ ] **Backend, both engines** — `cd backend && uv run pytest -q -p no:logging`, then the PostgreSQL leg. **Only one PostgreSQL run at a time**, and never while an implementer or a mutating reviewer is active.
- [ ] **Frontend** — `npx vitest run && npx tsc --noEmit && npm run lint`.
- [ ] **Confirm `test_an_agreement_changes_no_booking_behaviour` passes.** If it does not, A3 blocks and the design has been violated.
- [ ] **Open a PR**

```bash
git push -u github feature/agreement-enforcement
gh pr create --repo pjgross/envmgr --base main --title "Phase 7 A3: usage-agreement warnings"
```

The body should state that A3 warns and never blocks, that the warning is computed while only the acknowledgement is stored, and that `usage_agreement` was not modified.
