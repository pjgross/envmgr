# Phase 7 B6 — Forward Contention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Contention that A4 already computes becomes visible on the calendar, in the bookings list and as a forward-looking count — so a clash weeks out is seen while moving a booking is still cheap.

**Architecture:** One shared batch function folds A4's per-pair verdicts into a per-booking state, using a single self-join that REUSES `conflict_service.conflicts_with` rather than restating the overlap rules. Two consumers: `GET /bookings` (whose page feeds the list column and the calendar markers) and a horizon-count endpoint. Nothing is stored and no write path is added anywhere.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async (backend); React 18 + TypeScript + MUI + FullCalendar + Redux Toolkit (frontend); pytest (dual engine: SQLite + PostgreSQL) and vitest.

**Spec:** [docs/superpowers/specs/2026-08-19-forward-contention-design.md](../specs/2026-08-19-forward-contention-design.md) — read it before Task 1.

## Global Constraints

Every task's requirements implicitly include all of these.

- **B6 ADDS NO WRITE PATH AT ALL.** No table, no column, no stored verdict, nothing refused, nothing transitioned. If you find yourself writing `db.add`, an `UPDATE`, or a new migration, stop — you are outside B6. `tests/test_b6_writes_nothing.py` (Task 8) is the guard.
- **REUSE `conflict_service.conflicts_with`; DO NOT WRITE A SECOND OVERLAP PREDICATE.** Its docstring says it exists to prevent exactly that, and it already has two consumers. B6 is the third.
- **"Live" means `conflict_service.TERMINAL_STATES` (`{"rejected", "closed"}`), NOT `booking_states.INACTIVE_BOOKING_STATUSES`.** The two sets are deliberately different — the conflict set counts drafts AS conflicts. The wrong one makes the calendar and the Conflicts panel disagree about whether a clash exists.
- **NO `GREATEST`/`LEAST` AND NO DIALECT DATE ARITHMETIC.** SQLite has no `GREATEST`. Task 3 shows the portable formulation of an overlap-interval test.
- **The count is of CONTENTIONS (pairs), never of bookings.** Two bookings clashing is one contention.
- **Only one side of a pair need be in the requested set.** A September booking may clash with an August–October one the calendar never renders. Requiring both sides hides exactly the long-running bookings most likely to collide.
- **The state map contains only CONTENDED bookings.** An absent key means no contention; there is deliberately no `none` state.
- **Once per response, never once per row.** A3 measured a 50-row page through a per-booking helper at ~150 queries.
- **`now` is a REQUIRED KEYWORD parameter** on every service function reachable from a route — no default, no `None` fallback. The route reads the clock once and passes it to the service and the response builder. B5 established this after shipping two clocks in one request.
- Every tenant-scoped query filters `tenant_id` via `current_user.active_tenant_id`, never `.tenant_id`.
- No `db.commit()` in services. Never fabricate a foreign key in a test — use `backend/tests/factories.py`.
- **Backend tests:** `cd backend && PYTHONPATH=. .venv/bin/pytest <paths> -q`. **NEVER `uv run pytest`** — it takes a lock that kills a concurrent suite run. **Never set `TEST_DATABASE_URL`**; the controller runs both engine legs.
- **Frontend tests:** `cd frontend && npx vitest run <path>`. `npx tsc --noEmit` must stay at ZERO errors and `npm run lint` at ZERO problems — `npm run build` is `tsc && vite build`.
- **Stage explicitly** with `git add <paths>` then `git commit -m`. NEVER `git commit -am`.
- **Branch:** `feature/phase7-b6-forward-contention` already exists and carries the spec commit. Work on it. Do not push or merge.

---

## File Structure

**Backend — create**
- `app/services/contention_forecast_service.py` — the overlap query, the fold, and the horizon count. Its own module so `booking_service` gains one import, not a second concern.
- `backend/tests/services/test_contention_forecast.py` — the query and the fold.
- `backend/tests/integration/test_contention_forecast_api.py` — both endpoints.
- `backend/tests/test_b6_writes_nothing.py` — the guard.

**Backend — modify**
- `app/api/v1/schemas/booking.py` — `contention_state` on the booking response
- `app/services/booking_service.py` — call the batch function once per response
- `app/api/v1/bookings.py` — the horizon-count route

**Frontend — create**
- `src/types/contentionForecast.ts`, `src/store/contentionForecastSlice.ts`
- `src/components/bookings/ContentionMarker.tsx` — the shared three-state marker, used by the calendar AND the list so the two cannot render differently
- `src/components/bookings/ContentionHorizon.tsx` — the summary
- Tests alongside each

**Frontend — modify**
- `src/pages/bookings/BookingCalendar.tsx`, `src/pages/bookings/BookingList.tsx`, `src/types/booking.ts`

---

## Task 1: The overlap query

**Files:**
- Create: `backend/app/services/contention_forecast_service.py`, `backend/tests/services/test_contention_forecast.py`

**Interfaces:**
- Consumes: `conflict_service.conflicts_with`, `conflict_service.TERMINAL_STATES`
- Produces: `async def overlapping_pairs(db, tenant_id, *, booking_ids=None, window=None) -> list[tuple[int, int]]` — normalised pairs, `(lower_id, higher_id)`

- [ ] **Step 1: Write the failing tests**

```python
"""B6 Task 1 — the overlap query. READS ONLY."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import contention_forecast_service as svc
from tests.factories import ensure_environment, make_booking

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_two_overlapping_bookings_are_one_normalised_pair(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    a = await make_booking(db_session, tenant.id, env.id,
                           start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, env.id,
                           start=NOW + timedelta(days=1), end=NOW + timedelta(days=4))

    pairs = await svc.overlapping_pairs(db_session, tenant.id)

    assert pairs == [(min(a.id, b.id), max(a.id, b.id))]


@pytest.mark.asyncio
async def test_bookings_on_different_environments_do_not_contend(db_session, tenant):
    e1 = await ensure_environment(db_session, tenant.id, slot=1)
    e2 = await ensure_environment(db_session, tenant.id, slot=2)
    await make_booking(db_session, tenant.id, e1.id, start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, tenant.id, e2.id, start=NOW, end=NOW + timedelta(days=3))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_touching_bookings_do_not_overlap(db_session, tenant):
    """Half-open [start, end) — one ending exactly as the other starts is not a
    clash. The same convention conflict_service uses."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=1))
    await make_booking(db_session, tenant.id, env.id,
                       start=NOW + timedelta(days=1), end=NOW + timedelta(days=2))

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_a_rejected_booking_does_not_contend(db_session, tenant):
    """TERMINAL_STATES is {rejected, closed} — and DRAFTS ARE NOT IN IT, so a
    draft DOES contend. That is conflict_service's rule and B6 must not invent
    a different one."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    dead = await make_booking(db_session, tenant.id, env.id,
                              start=NOW, end=NOW + timedelta(days=3))
    dead.status = "rejected"
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_a_draft_booking_does_contend(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    a = await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    b.status = "draft"
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == [
        (min(a.id, b.id), max(a.id, b.id))
    ]


@pytest.mark.asyncio
async def test_a_soft_deleted_booking_does_not_contend(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    gone = await make_booking(db_session, tenant.id, env.id,
                              start=NOW, end=NOW + timedelta(days=3))
    gone.deleted_at = NOW
    await db_session.flush()

    assert await svc.overlapping_pairs(db_session, tenant.id) == []


@pytest.mark.asyncio
async def test_another_tenants_bookings_never_pair(db_session, tenant, other_tenant):
    """Both sides must be in the tenant. A pair spanning two tenants is not a
    contention, it is a bug in whatever created it."""


@pytest.mark.asyncio
async def test_only_one_side_need_be_in_the_requested_set(db_session, tenant):
    """LOAD-BEARING. A booking shown in September may clash with one running
    August to October that the calendar never renders. Requiring both sides in
    the set would hide exactly the long-running bookings most likely to
    collide."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    september = await make_booking(db_session, tenant.id, env.id,
                                   start=NOW, end=NOW + timedelta(days=2))
    spanning = await make_booking(db_session, tenant.id, env.id,
                                  start=NOW - timedelta(days=40),
                                  end=NOW + timedelta(days=40))

    pairs = await svc.overlapping_pairs(db_session, tenant.id, booking_ids=[september.id])

    assert pairs == [(min(september.id, spanning.id), max(september.id, spanning.id))]


@pytest.mark.asyncio
async def test_each_pair_appears_once_not_twice(db_session, tenant):
    """`b1.id < b2.id` normalises. Without it every clash is reported twice and
    the horizon count doubles."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))

    assert len(await svc.overlapping_pairs(db_session, tenant.id)) == 1
```

Fill in `test_another_tenants_bookings_never_pair` following the pattern above: create an environment and two overlapping bookings under `other_tenant`, plus one under `tenant`, and assert `overlapping_pairs(db_session, tenant.id)` returns only the pair belonging to `tenant`. If `conftest.py` has no `other_tenant` fixture, use the `tenant` and `test_tenant` fixtures, which ARE two different tenants — read their docstrings first, and say in your report which you used.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/pytest tests/services/test_contention_forecast.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.contention_forecast_service'`.

- [ ] **Step 3: Write the query**

```python
"""B6 — forward contention: which bookings clash, folded per booking.

READS ONLY. Nothing in this module writes, and it must never learn how —
`tests/test_b6_writes_nothing.py` is the guard on that.

The overlap rules are NOT restated here. `conflict_service.conflicts_with` is
the one definition and already had two consumers before B6; this is the third.
A second copy is the "two mechanisms enforcing one outcome" shape that has cost
this codebase repeatedly, and a calendar that disagreed with the Conflicts
panel about whether a clash exists would be worse than no calendar marker.
"""
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.booking import Booking
from app.services import conflict_service


async def overlapping_pairs(
    db: AsyncSession,
    tenant_id: int,
    *,
    booking_ids: Optional[Sequence[int]] = None,
    window: Optional[tuple[datetime, datetime]] = None,
) -> list[tuple[int, int]]:
    """Every live overlapping pair in this tenant, normalised `(lower, higher)`.

    THE DATABASE DOES THE PAIRING. Contention is pairwise, so a Python-side
    implementation is O(N^2) over a calendar's worth of bookings. Overlaps are
    sparse in real estates, so the cost here scales with the number of actual
    clashes rather than with how busy the calendar looks.

    `b1.id < b2.id` does two jobs: it halves the work, and it yields A4's
    normalised pair directly, so `escalations_for_pairs` — which keys by the
    pair AS GIVEN — matches without a second normalisation step.

    ONLY ONE SIDE NEED BE IN `booking_ids`. See the spec: requiring both would
    silently hide a long-running booking that the caller's range never renders,
    and the omission looks exactly like an absence of contention.
    """
    b1 = aliased(Booking)
    b2 = aliased(Booking)

    # conflict_service filters only the OTHER side; the subject's own liveness
    # is the caller's job there (`list_conflicts` checks it separately), so B6
    # applies the same three conditions to b1 itself.
    query = (
        select(b1.id, b2.id)
        .select_from(b1)
        .join(
            b2,
            and_(
                *conflict_service.conflicts_with(
                    b2,
                    subject_id=b1.id,
                    environment_id=b1.environment_id,
                    start_date=b1.start_date,
                    end_date=b1.end_date,
                    tenant_id=tenant_id,
                )
            ),
        )
        .where(
            b1.tenant_id == tenant_id,
            b1.deleted_at.is_(None),
            b1.status.notin_(conflict_service.TERMINAL_STATES),
            b1.id < b2.id,
        )
    )

    if booking_ids is not None:
        ids = list(booking_ids)
        if not ids:
            return []
        query = query.where(or_(b1.id.in_(ids), b2.id.in_(ids)))

    if window is not None:
        start, end = window
        # THE OVERLAP INTERVAL, WITHOUT GREATEST/LEAST — SQLite has neither.
        # max(b1.start, b2.start) <  end  <=>  b1.start < end  AND b2.start < end
        # min(b1.end,   b2.end)   > start <=>  b1.end   > start AND b2.end   > start
        query = query.where(
            b1.start_date < end, b2.start_date < end,
            b1.end_date > start, b2.end_date > start,
        )

    rows = (await db.execute(query.order_by(b1.id, b2.id))).all()
    return [(low, high) for low, high in rows]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && PYTHONPATH=. .venv/bin/pytest tests/services/test_contention_forecast.py -q`
Expected: PASS.

- [ ] **Step 5: Prove two tests discriminate**

Break each rule, confirm the named test fails, revert, confirm `git diff` is clean. Record both runs.
- Remove `b1.id < b2.id` → `test_each_pair_appears_once_not_twice` must fail.
- Change `or_(b1.id.in_(ids), b2.id.in_(ids))` to `and_(...)` → `test_only_one_side_need_be_in_the_requested_set` must fail.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/contention_forecast_service.py backend/tests/services/test_contention_forecast.py
git commit -m "feat(b6): the overlap query, reusing conflict_service's one definition"
```

---

## Task 2: The fold

**Files:**
- Modify: `backend/app/services/contention_forecast_service.py`, `backend/tests/services/test_contention_forecast.py`

**Interfaces:**
- Consumes: `overlapping_pairs` (Task 1); `contention_service.escalations_for_pairs(db, pairs, tenant_id)`, `.escalation_state(escalation, now)`, `.STATE_ANSWERED`
- Produces: `STATE_UNOWNED`/`STATE_OWNED`/`STATE_DECIDED`; `async def contention_states_for_bookings(db, tenant_id, booking_ids, *, now) -> dict[int, str]`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_a_clash_with_no_escalation_is_unowned(db_session, tenant):
    env = await ensure_environment(db_session, tenant.id, slot=1)
    a = await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))
    b = await make_booking(db_session, tenant.id, env.id, start=NOW, end=NOW + timedelta(days=3))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [a.id, b.id], now=NOW
    )

    assert states == {a.id: svc.STATE_UNOWNED, b.id: svc.STATE_UNOWNED}


@pytest.mark.asyncio
async def test_an_open_escalation_is_owned(db_session, tenant):
    """A4's `open` — someone owns it and the deadline is running."""


@pytest.mark.asyncio
async def test_an_expired_escalation_is_still_owned(db_session, tenant):
    """A4's third state renders as `owned`, not a fourth marker: an overdue
    escalation still has a NAMED OWNER who owes an answer. The booking's own
    page says it is overdue."""


@pytest.mark.asyncio
async def test_an_answered_escalation_is_decided(db_session, tenant):
    """And the pair is STILL reported — A4 moves no booking, so the two
    bookings genuinely still overlap until a human reschedules one."""


@pytest.mark.asyncio
async def test_an_uncontended_booking_is_absent_from_the_map(db_session, tenant):
    """ABSENT, not a `none` state. A four-valued enum whose fourth value means
    "nothing to say" invites a consumer to render it, and an empty chip reads
    as a state of its own."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    lonely = await make_booking(db_session, tenant.id, env.id,
                                start=NOW, end=NOW + timedelta(days=1))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [lonely.id], now=NOW
    )

    assert states == {}


@pytest.mark.asyncio
async def test_the_most_actionable_state_wins(db_session, tenant):
    """A booking in three contentions shows the one that needs a human:
    unowned beats owned beats decided. Reverse the precedence and this fails."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    hub = await make_booking(db_session, tenant.id, env.id,
                             start=NOW, end=NOW + timedelta(days=10))
    # one decided, one owned, one unowned — build them with escalations as the
    # three tests above do, then:
    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [hub.id], now=NOW
    )
    assert states[hub.id] == svc.STATE_UNOWNED


@pytest.mark.asyncio
async def test_the_counterpart_outside_the_set_is_not_reported(db_session, tenant):
    """Only requested bookings get a state. The long-running counterpart is
    used to DECIDE the state, not to appear in the answer — otherwise a
    calendar month would render markers on bookings it never drew."""
    env = await ensure_environment(db_session, tenant.id, slot=1)
    shown = await make_booking(db_session, tenant.id, env.id,
                               start=NOW, end=NOW + timedelta(days=2))
    spanning = await make_booking(db_session, tenant.id, env.id,
                                  start=NOW - timedelta(days=40),
                                  end=NOW + timedelta(days=40))

    states = await svc.contention_states_for_bookings(
        db_session, tenant.id, [shown.id], now=NOW
    )

    assert set(states) == {shown.id}
    assert spanning.id not in states
```

Fill in the four bodies marked with a docstring only, following the shape of `test_a_clash_with_no_escalation_is_unowned` above. For the escalation ones, create a `ContentionEscalation` on the normalised pair using `backend/tests/factories.py` helpers if one exists, or construct it directly with `ensure_user` for `owner_user_id` — never fabricate a user id. An `open` escalation has `decided_at = None` and `respond_by` in the future; an `expired` one has `decided_at = None` and `respond_by` in the past; an `answered` one has `decided_at` set. Read `contention_service.escalation_state` first — it is the authority on which is which, and its branch order matters.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && PYTHONPATH=. .venv/bin/pytest tests/services/test_contention_forecast.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'contention_states_for_bookings'`.

- [ ] **Step 3: Write the fold**

```python
STATE_UNOWNED = "unowned"
STATE_OWNED = "owned"
STATE_DECIDED = "decided"

#: Most actionable first. The fold keeps whichever appears earlier here.
#: "Nobody is on this" is the state that needs a human, so it outranks a
#: contention someone already owns, which outranks one already decided.
_PRECEDENCE = (STATE_UNOWNED, STATE_OWNED, STATE_DECIDED)


def _more_actionable(current: Optional[str], candidate: str) -> str:
    if current is None:
        return candidate
    return min(current, candidate, key=_PRECEDENCE.index)


async def contention_states_for_bookings(
    db: AsyncSession,
    tenant_id: int,
    booking_ids: Sequence[int],
    *,
    now: datetime,
) -> dict[int, str]:
    """The contention state of each REQUESTED booking that has one.

    ONCE PER RESPONSE, NEVER ONCE PER ROW. A3 measured a 50-row page through a
    per-booking helper at roughly 150 queries; this takes the whole page's ids
    and issues two.

    Absent key == no contention. There is deliberately no `none` state.
    """
    requested = set(booking_ids)
    if not requested:
        return {}

    pairs = await overlapping_pairs(db, tenant_id, booking_ids=list(requested))
    if not pairs:
        return {}

    escalations = await contention_service.escalations_for_pairs(db, pairs, tenant_id)

    states: dict[int, str] = {}
    for pair in pairs:
        escalation = escalations.get(pair)
        if escalation is None:
            pair_state = STATE_UNOWNED
        elif contention_service.escalation_state(escalation, now) == (
            contention_service.STATE_ANSWERED
        ):
            pair_state = STATE_DECIDED
        else:
            # `open` AND `expired`. An overdue escalation still has a named
            # owner who owes an answer; the booking's own page says so.
            pair_state = STATE_OWNED

        for booking_id in pair:
            if booking_id not in requested:
                # The counterpart decides the state; it does not get one.
                continue
            states[booking_id] = _more_actionable(states.get(booking_id), pair_state)

    return states
```

Add `from app.services import contention_service` to the imports.

- [ ] **Step 4: Run the tests to verify they pass, then prove the precedence discriminates**

Reverse `_PRECEDENCE` and confirm `test_the_most_actionable_state_wins` fails; revert; confirm `git diff` clean. Record both runs.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/contention_forecast_service.py backend/tests/services/test_contention_forecast.py
git commit -m "feat(b6): fold each booking's contentions into one actionable state"
```

---

## Task 3: The horizon count

**Files:**
- Modify: `backend/app/services/contention_forecast_service.py`, `backend/app/api/v1/bookings.py`
- Create: `backend/tests/integration/test_contention_forecast_api.py`

**Interfaces:**
- Produces: `async def contention_count_in_window(db, tenant_id, *, start, end) -> int`; route `GET /bookings/contention-horizon?weeks=<int>`

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_count_is_of_contentions_not_bookings(client, auth_headers, ...):
    """TWO BOOKINGS CLASHING IS ONE CONTENTION. Counting marked bookings
    double-counts every pair and inflates the headline number this feature
    exists to make trustworthy. Build a fixture where the two numbers differ:
    three mutually overlapping bookings are THREE pairs and THREE bookings, so
    use two separate clashes instead — 4 bookings, 2 contentions."""
    r = await client.get("/api/v1/bookings/contention-horizon?weeks=6", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["count"] == 2


@pytest.mark.asyncio
async def test_a_clash_beyond_the_horizon_is_not_counted(client, auth_headers, ...):
    """Two bookings that start clashing in four months are not a contention in
    the next six weeks."""


@pytest.mark.asyncio
async def test_the_horizon_tests_the_overlap_interval_not_either_booking(client, auth_headers, ...):
    """LOAD-BEARING. A booking starting tomorrow that runs for a year, clashing
    with one that starts in four months, is NOT a contention in the next six
    weeks — the pair does not overlap until month four. Defining the horizon on
    either booking's start would report a clash that cannot happen yet."""


@pytest.mark.asyncio
async def test_widening_the_horizon_finds_more(client, auth_headers, ...):
    """?weeks=26 sees a clash that ?weeks=2 does not."""


@pytest.mark.asyncio
async def test_an_out_of_range_weeks_value_is_422(client, auth_headers):
    r = await client.get("/api/v1/bookings/contention-horizon?weeks=0", headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_another_tenants_contentions_are_not_counted(client, auth_headers, ...):
    ...
```

Fill in each body. Use `test_tenant` and `auth_headers` together — they belong to the same tenant. **Do NOT combine the `tenant` fixture with `auth_headers`**: they are DIFFERENT tenants and the test would pass vacuously by querying across them. `conftest.py`'s docstring says so.

- [ ] **Step 2: Run to verify they fail** — Expected: 404 on the route.

- [ ] **Step 3: Write the count**

```python
async def contention_count_in_window(
    db: AsyncSession, tenant_id: int, *, start: datetime, end: datetime
) -> int:
    """How many CONTENTIONS fall inside the window — pairs, never bookings.

    A contention is inside the window when its OVERLAP INTERVAL is: the
    intersection of the two bookings, not either booking's own span. A pair
    that starts clashing in four months is not a contention in the next six
    weeks even if one of its bookings begins tomorrow.
    """
    return len(await overlapping_pairs(db, tenant_id, window=(start, end)))
```

- [ ] **Step 4: Write the route** in `app/api/v1/bookings.py`

`weeks: int = Query(6, ge=1, le=104)` — the default is six weeks (roughly two sprints: far enough out to act, near enough to matter), and the bound is two years. Take the clock ONCE at the top of the endpoint, compute `start = now` and `end = now + timedelta(weeks=weeks)`, call `contention_forecast_service.contention_count_in_window(db, current_user.active_tenant_id, start=start, end=end)`, and return `{"count": <int>, "weeks": weeks}` so the client can echo back what it asked for rather than assuming.

Cross-tenant is not reachable here — the count is always scoped to `current_user.active_tenant_id`.

- [ ] **Step 5: Run the tests, then commit**

```bash
git add backend/app/services/contention_forecast_service.py backend/app/api/v1/bookings.py backend/tests/integration/test_contention_forecast_api.py
git commit -m "feat(b6): the forward-contention horizon count"
```

---

## Task 4: `contention_state` on the booking response

**Files:**
- Modify: `backend/app/api/v1/schemas/booking.py`, `backend/app/services/booking_service.py`, `backend/app/api/v1/bookings.py`
- Modify: `backend/tests/integration/test_contention_forecast_api.py`

**Interfaces:**
- Produces: `BookingResponse.contention_state: Optional[str]` — the state, or null when the booking has no contention

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_the_list_carries_the_contention_state(client, auth_headers, ...):
    """Over HTTP, asserting the VALUE — not merely that the key is present.
    B5 shipped `idle` computed, filterable and absent from the response, and it
    took a reviewer asking "what consumes this?" to catch it."""
    rows = (await client.get("/api/v1/bookings/", headers=auth_headers)).json()
    contended = next(r for r in rows if r["id"] == clashing.id)
    assert contended["contention_state"] == "unowned"


@pytest.mark.asyncio
async def test_an_uncontended_booking_carries_null(client, auth_headers, ...):
    """Null, and the grid cell renders NOTHING for it — never an empty chip."""


@pytest.mark.asyncio
async def test_the_list_issues_no_query_per_row(client, auth_headers, ...):
    """Structural guard: a page of N bookings must not cost N lookups. Assert
    on the number of statements executed for a 1-row page versus a 5-row page —
    they must be EQUAL. A3's rule; a 50-row page through a per-booking helper
    measured ~150 queries."""
```

Fill in the third test using whatever query-counting facility the suite already has; if none exists, use SQLAlchemy's `event.listen(engine, "before_cursor_execute", ...)` to count statements around each request, and say in your report that you added it.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Wire it**

`booking_service.list_bookings` calls `contention_states_for_bookings` ONCE with the page's booking ids, then hands the map to the response builder. `BookingResponse.contention_state` is `Optional[str]`, set explicitly from the map with `.get(booking.id)` — it cannot come from `model_validate`, since no column backs it.

**Do NOT add `contention_state` to `BOOKING_SORTS`** — it is folded after the page is fetched, and whitelisting it would 500 on a bare `?sort_by=contention_state`. **Do NOT add a filter** — `/contentions` is the filtering surface, and a filter here needs a second definition of the fold.

The clock is taken ONCE in the endpoint and passed to `list_bookings`.

- [ ] **Step 4: Run the tests, then commit**

```bash
git commit -m "feat(b6): contention_state on the booking response, folded once per page"
```

---

## Task 5: Frontend types, slice, and the shared marker

**Files:**
- Create: `frontend/src/types/contentionForecast.ts`, `frontend/src/store/contentionForecastSlice.ts`, `frontend/src/components/bookings/ContentionMarker.tsx`, and tests for each
- Modify: `frontend/src/types/booking.ts`, `frontend/src/store/index.ts`

**Interfaces:**
- Produces: `ContentionState = 'unowned' | 'owned' | 'decided'`; `Booking.contention_state: ContentionState | null`; `fetchContentionHorizon` thunk; `<ContentionMarker state={...} />`

**ONE MARKER COMPONENT, USED BY BOTH THE CALENDAR AND THE LIST.** Three copies of a state→label map already exist in this codebase from B5 and nothing would catch a future edit to one and not the others. B6 ships one component so the two surfaces cannot render the same state differently.

- [ ] **Step 1: Write the failing tests**

```tsx
import { render, screen } from '@testing-library/react';
import { AxiosError } from 'axios';

describe('ContentionMarker', () => {
  it('renders a distinct label for each of the three states', () => {
    for (const [state, label] of [
      ['unowned', /needs escalating/i],
      ['owned', /awaiting a decision/i],
      ['decided', /decided/i],
    ] as const) {
      const { unmount } = render(<ContentionMarker state={state} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it('does not rely on colour alone', () => {
    // This repo has a completed a11y audit and colour-only state encoding is
    // exactly what it flags. Every state must carry text or an aria-label.
    render(<ContentionMarker state="owned" />);
    expect(screen.getByRole('img', { hidden: true })).toHaveAttribute('aria-label');
  });
});

describe('contentionForecastSlice', () => {
  it('surfaces the server reason, not the HTTP status', async () => {
    // RTK's miniSerializeError drops response.data.detail; a test rejecting
    // with a plain Error carrying the final text PASSES WHILE THE APP IS
    // BROKEN. Mock the AxiosError shape.
    const err = new AxiosError('Request failed with status code 422');
    err.response = { data: { detail: 'weeks must be between 1 and 104' },
                     status: 422, statusText: '', headers: {}, config: {} as never };
    vi.mocked(api.get).mockRejectedValueOnce(err);

    const result = await store.dispatch(fetchContentionHorizon(0));

    expect(result.payload).toContain('weeks must be between 1 and 104');
  });
});
```

Adjust the exact label wording to whatever reads best, but keep the three distinguishable and keep the assertion on rendered text rather than on a class name.

- [ ] **Step 2: Run to verify they fail.** `cd frontend && npx vitest run src/components/bookings/__tests__/ContentionMarker.test.tsx`

- [ ] **Step 3: Implement.** The thunk uses `rejectWithValue(formatApiError(err))` from `src/services/apiError.ts`; every caller reads `result.payload`, never `result.error.message`.

- [ ] **Step 4: Prove the error test discriminates** — drop `rejectWithValue(formatApiError(...))`, confirm the AxiosError test fails, revert, confirm `git diff` clean.

- [ ] **Step 5: Run tests and `npx tsc --noEmit`, then commit**

```bash
git commit -m "feat(b6): contention types, horizon slice, and the shared marker"
```

---

## Task 6: The BookingList column

**Files:**
- Modify: `frontend/src/pages/bookings/BookingList.tsx`
- Create: `frontend/src/pages/bookings/__tests__/bookingListContention.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it('renders the marker only for contended rows', async () => { /* two rows, one null */ });

it('renders nothing at all for a null state', async () => {
  // Never an empty chip — an empty chip reads as a state of its own.
});

it('does not offer Contention as a sortable column', () => {
  const columns = buildBookingColumns(defaultArgs);
  expect(columns.find((c) => c.field === 'contention_state')!.sortable).toBe(false);
});

it('has no custom-field column whose field collides with a static one', () => {
  // BookingList was namespaced cf_<key> in August after a colliding key made
  // MUI emit a visibility change that saveColumnModel PERSISTED, silently
  // hiding a real column. No fixture defines a colliding custom field, so only
  // this structural assertion can catch it.
  const columns = buildBookingColumns({
    ...defaultArgs,
    customFields: [{ field_key: 'contention_state', label: 'Contention?' }],
  });
  const fields = columns.map((c) => c.field);
  expect(new Set(fields).size).toBe(fields.length);
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement** using `<ContentionMarker />` — do not write a second state→label map.

- [ ] **Step 4: Prove the non-sortable test discriminates**, run `npx tsc --noEmit`, commit.

```bash
git commit -m "feat(b6): the contention column on the bookings list"
```

---

## Task 7: Calendar markers

**Files:**
- Modify: `frontend/src/pages/bookings/BookingCalendar.tsx`
- Create: `frontend/src/pages/bookings/__tests__/bookingCalendarContention.test.tsx`

- [ ] **Step 1: Write the failing tests** — a contended event carries the marker; an uncontended one carries nothing; the three states are distinguishable; clicking still opens the booking detail unchanged.

**jsdom cannot reliably render FullCalendar.** If an assertion is blocked by that, assert on the event-content render function's output or the props handed to it, and SAY SO PLAINLY in your report rather than writing an assertion that passes because it found nothing. A test searching a calendar that rendered no events passes for the worst possible reason. B5 hit exactly this with DataGrid and solved it with an un-virtualised stand-in — look at `src/pages/environments/__tests__/environmentIdleColumn.test.tsx` for the pattern before deciding it cannot be done.

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** The calendar already fetches bookings for its visible range; `contention_state` arrives on those rows, so this adds no new fetch. Use `<ContentionMarker />`.

- [ ] **Step 4: Run tests, `npx tsc --noEmit`, commit**

```bash
git commit -m "feat(b6): contention markers on the booking calendar"
```

---

## Task 8: The horizon summary

**Files:**
- Create: `frontend/src/components/bookings/ContentionHorizon.tsx` + test
- Modify: `frontend/src/pages/bookings/BookingCalendar.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it('shows the count for the default six-week horizon', async () => { /* … */ });

it('is independent of the month being viewed', async () => {
  // THE WHOLE LEADING-INDICATOR CLAIM. Navigate the calendar to another month
  // and assert the horizon count does NOT change and no horizon refetch fires.
  // If it tracks the visible range it is not a leading indicator, because you
  // only learn about November by navigating to November.
});

it('widening the horizon refetches with the new value', async () => {
  await userEvent.click(screen.getByRole('button', { name: /26 weeks/i }));
  await waitFor(() => {
    expect(api.get).toHaveBeenCalledWith(
      expect.stringContaining('weeks=26'), expect.anything(),
    );
  });
});

it('puts the chosen horizon in the URL', async () => { /* shareable view */ });

it('links through to the contentions worklist', async () => {
  // B6 builds no second worklist; /contentions already filters by state.
});

it('says "1 contention" not "1 contentions"', async () => {
  // Small, but this is a headline number people will quote.
});
```

- [ ] **Step 2: Run to verify they fail.**

- [ ] **Step 3: Implement.** Horizon options 2 / 6 / 12 / 26 weeks, default 6, held in the URL. The component dispatches `fetchContentionHorizon(weeks)` from Task 5's slice on mount and on every change of the selected horizon — and on NOTHING else, in particular not on a calendar month change, which is what the independence test pins.

- [ ] **Step 4: Prove the independence test discriminates** — make the horizon follow the calendar's visible range, confirm that test fails, revert, confirm clean. Record it: that mutation is the difference between a leading indicator and a restatement of the current month.

- [ ] **Step 5: Run tests, `npx tsc --noEmit`, `npm run lint`, commit**

```bash
git commit -m "feat(b6): the forward-contention horizon summary"
```

---

## Task 9: The guard

**Files:**
- Create: `backend/tests/test_b6_writes_nothing.py`

**B6 IS THE FIRST PURE-READ SUB-PROJECT IN PHASE 7.** A3 warns, A4 advises, B2 advises, B5 acts narrowly and pins exactly how far. B6 touches nothing, and this file is the guard on that.

- [ ] **Step 1: Write the guard**

```python
"""B6 TOUCHES NOTHING.

B6 adds no table, no column, no stored verdict, and no write path of any kind.
It reads bookings and A4's escalations and renders them somewhere new.

IF ANY TEST HERE FAILS, B6 HAS STARTED WRITING.

Prove this file non-vacuous before trusting it: make `contention_states_for_
bookings` stamp anything at all onto a booking it inspects, watch
`test_reading_contention_changes_no_row` fail, then revert.
"""

@pytest.mark.asyncio
async def test_reading_contention_changes_no_row(db_session, tenant, populated_estate):
    """Snapshot EVERY column of every booking, environment, escalation and
    deployment; fold contention over the whole estate; compare the whole
    mapping. Asserting on one column is how a guard passes while the thing it
    guards has changed."""


@pytest.mark.asyncio
async def test_the_horizon_count_changes_no_row(db_session, tenant, populated_estate):
    ...


@pytest.mark.asyncio
async def test_listing_bookings_with_contention_changes_no_row(client, auth_headers, populated_estate):
    """Through HTTP, since that is the path a user actually takes."""


@pytest.mark.asyncio
async def test_b6_adds_no_migration():
    """Structural, and a SMOKE ALARM rather than a proof: the alembic head is
    unchanged from the branch point, so B6 introduced no schema change. A
    bounded check — it would not catch a raw DDL statement executed at runtime,
    and it says so."""


@pytest.mark.asyncio
async def test_no_b6_module_writes(db_session):
    """Structural, and a SMOKE ALARM rather than a proof: grep
    `contention_forecast_service` for `db.add`, `db.delete`, `update(`,
    `insert(` and `delete(`. A substring scan of one file with no call-graph
    following; an aliased import or a write in a helper it calls would pass.
    Labelled as such, following B4's and B5's precedent."""
```

Use `backend/tests/factories.py` throughout. `populated_estate` should build two tenants' worth of environments, bookings (including clashing ones), deployments and at least one escalation — "nothing changed" over an empty database is trivially true.

- [ ] **Step 2: Prove the file is non-vacuous.** Make the fold write something — the simplest is to set an attribute on a loaded `Booking` inside `contention_states_for_bookings` so the session flushes it. Run the file: `test_reading_contention_changes_no_row` MUST fail. Revert, confirm `git diff` clean, run again, all pass. Record both runs verbatim.

- [ ] **Step 3: Commit**

```bash
git commit -m "test(b6): the guard — B6 touches nothing"
```

---

## Task 10: Documentation

**Files:** `docs/phases/phase-7.md`, `CLAUDE.md`, `docs/user-guide.md`, `docs/pagination.md`

- [ ] **Step 1: `docs/phases/phase-7.md`** — tick B6, add "What B6 established" in the same voice as the B5 and A4 sections directly above. Cover: B6 is the first pure-read sub-project and `test_b6_writes_nothing.py` is its guard; the overlap rules are `conflict_service.conflicts_with`'s and B6 is its third consumer, not a second copy; "live" is `conflict_service.TERMINAL_STATES` so drafts count; the count is pairs not bookings; only one side of a pair need be in the requested set; the horizon tests the overlap INTERVAL, not either booking's span; the fold precedence and why unowned outranks owned; decided contentions stay visible because A4 moves nothing; and the §2.12 deviation that B6 predicts nothing.

- [ ] **Step 2: `CLAUDE.md`** — a B6 block, plus a pitfall: *using `GREATEST`/`LEAST` for an interval test* — SQLite has neither, and `max(a,b) < X` decomposes to `a < X AND b < X` with no dialect function at all. **PHASE 7 IS COMPLETE with B6** — update the phase status line accordingly.

- [ ] **Step 3: `docs/user-guide.md`** — what a contention marker means, what the three states ask of you, why a decided contention still shows, and that the horizon is independent of the month you are looking at.

- [ ] **Step 4: `docs/pagination.md`** — add `contention_state` to the permanently-unsortable set with its reason (folded per response after the page is fetched), and note that it is deliberately not filterable because `/contentions` is the filtering surface.

- [ ] **Step 5: Commit**

```bash
git commit -m "docs(b6): forward contention in the guides, phase-7 and the pitfalls"
```

---

## Task 11: Whole-branch verification

- [ ] **Step 1: Both full suites.** Background, redirected to a log, polled with an until-loop — they exceed the foreground limit. Expected: zero failures on both engines.

- [ ] **Step 2: `npx tsc --noEmit`, `npm run lint`, `npm run build`** — all clean. Note `npm run lint` uses `--report-unused-disable-directives --max-warnings 0`, so an unused `eslint-disable` is a hard error; both B4 and B5 shipped one.

- [ ] **Step 3: The mutation pass.** Break each rule, confirm a NAMED test fails, revert:

| Mutation | Test that must fail |
|---|---|
| Remove `b1.id < b2.id` | `test_each_pair_appears_once_not_twice` |
| `or_` → `and_` on the booking-ids filter | `test_only_one_side_need_be_in_the_requested_set` |
| Reverse `_PRECEDENCE` | `test_the_most_actionable_state_wins` |
| Use `INACTIVE_BOOKING_STATUSES` instead of `TERMINAL_STATES` | `test_a_draft_booking_does_contend` |
| Horizon tests either booking's span instead of the overlap interval | `test_the_horizon_tests_the_overlap_interval_not_either_booking` |
| Count bookings instead of pairs | `test_the_count_is_of_contentions_not_bookings` |
| Horizon follows the calendar's visible range | `it('is independent of the month being viewed')` |
| Make the fold write to a booking | `test_reading_contention_changes_no_row` |

**Any mutation that leaves the suite green is a missing test, not a passing mutation.** B5 found five such rules; A4 found six of seven survivors sitting on the rules its comments explained best.

- [ ] **Step 4: A browser pass.** Create two clashing bookings weeks out; confirm the calendar marks both and the marker distinguishes state; escalate one and confirm it changes to owned; record a decision and confirm it changes to decided AND STILL SHOWS; check the horizon count matches the number of pairs, not bookings; widen the horizon and watch it change; navigate months and confirm the horizon does NOT change; follow the link to `/contentions`; confirm the list column agrees with the calendar for the same booking.

- [ ] **Step 5: Commit and hand back.** Do not merge.

```bash
git commit -m "test(b6): whole-branch verification — dual engine, mutation pass, browser pass"
```
