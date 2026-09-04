# PR 3 — Dashboard & My work: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer "what is waiting on me?" with a `/my-work` inbox of five queues, and turn the Phase-0 placeholder dashboard into a landing page of live counts — without restating a single filter predicate that already exists.

**Architecture:** One new endpoint, `GET /api/v1/me/work`, composes the four already-exposed service query seams (`contention_service.worklist_query`, `pir_finding_service.worklist_query`, `environment_decommission_service.worklist_query`, `environment_request_service.actionable_clause`) under **one clock**, and returns five queues' counts plus their five most urgent rows. Two backend gaps found before planning are filled first: `GET /bookings` gains SQL interval-overlap range filters, and the decommission seam gains optional group-membership narrowing. The frontend adds `/my-work`, four dashboard tiles reading `X-Total-Count` from `limit=1` fetches of existing list endpoints, and a nav badge — no new aggregation endpoints, no polling.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + PostgreSQL/SQLite (both test legs), React 18 + TypeScript strict + MUI 5 + Redux Toolkit, Vitest + Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-frontend-ia-and-shell-design.md` — §5 (this PR), §9 (testing), §11 (decisions). **§5 was amended three times on 2026-09-04, immediately before this plan**, and the amendments are the parts most likely to be got wrong. Read §5 in full first.

## Global Constraints

- **NO RESTATED PREDICATES.** Every count calls an existing service seam. A second implementation of "which contentions are open for me" is the defect this PR is most likely to ship, and it would look correct for months. §9's count-equivalence test is the guard.
- **ONE CLOCK.** `now` is taken **once** per request and threaded through every queue. `expiry_boundary(now)` decides overdue and decommission state — the day-not-instant rule A4, B2, B5, C2 and the PIR work all follow. Two `datetime.now()` calls in one response can disagree across midnight.
- **`/me/work` DEGRADES PER QUEUE.** One failing queue returns marked-as-failed; it never fails the whole request, and it is never rendered as empty. "Nothing waiting on you" must never be the rendering of "we could not tell".
- **THE DECOMMISSION QUEUE IS NARROWED BY MEMBERSHIP FOR EVERYONE, ADMINS INCLUDED.** §5's "(Admin: all)" was struck — see the spec and `environment_request_service.actionable_clause`'s docstring for why. An Admin in no operations group correctly sees an empty card.
- **Items carry display names with the row** (environment name, release name, owner username), never bare ids. `usernames_for` is **not** tenant-qualified (A4/C2: under master-admin impersonation the person can sit outside the row's tenant).
- Backend: `native_enum=False` on any enum column; never `db.commit()` in a service (`get_db` commits; use `flush()`); every tenant-scoped query filters `current_user.active_tenant_id`, **not** `.tenant_id`.
- **Three suite runs, not one.** SQLite (`uv run pytest -q`), PostgreSQL (`TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`, **run alone** — two concurrent PG sessions drop each other's tables), and the frontend (`npx vitest run`).
- Frontend gate before every commit touching `.ts`/`.tsx`: `npx tsc --noEmit && npm run lint` (`--max-warnings 0`). A function exported from a component file trips `react-refresh/only-export-components` — hooks and helpers go in their own file.
- Run a **floor**, not a whitelist: backend `uv run pytest -q`, frontend `npx vitest run src/pages src/components src/__tests__ src/hooks`. In PR 2 a named list of test files omitted a task's own page tests and left five tests red for five tasks.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Ld4MWKmSqoYRbsSpm9WpTR
  ```
- Branch: `feature/ia-dashboard-my-work` (already created; the two §5 amendments are its first commits).

---

## File map

**Backend — created**

| File | Responsibility |
|---|---|
| `app/api/v1/me.py` | The `/me/work` route. Thin: takes one clock, calls the service, shapes the response. |
| `app/services/my_work_service.py` | Composes the five queues from existing seams. Owns per-queue failure isolation. No new predicates. |
| `app/schemas/my_work.py` | `MyWorkResponse`, `QueueResult`, `WorkItem`. |
| `tests/test_me_work_matches_worklists.py` | §9's count-equivalence test — the guard on "no restated predicates". |
| `tests/test_bookings_range_filter.py` | Overlap semantics for the new `start`/`end`. |

**Backend — modified**

| File | Change |
|---|---|
| `app/api/v1/bookings.py` | `start`/`end` query params (~line 204, beside `project_id`). |
| `app/services/booking_service.py` | SQL interval-overlap clause in `list_bookings`. |
| `app/services/environment_decommission_service.py:820` | `worklist_query` gains optional `member_user_id`. |
| `app/services/environment_request_service.py:416` | `_actionable_clause` → `actionable_clause` (public); update its existing caller. |
| `app/main.py:~94,~139` | Import and include the new router. |

**Frontend — created**

| File | Responsibility |
|---|---|
| `src/pages/MyWork.tsx` | The page: five queue cards. |
| `src/components/mywork/QueueCard.tsx` | One card: count, up to five rows, "View all →", empty state, failed state. |
| `src/services/myWorkService.ts` | `GET /me/work` client. |
| `src/store/myWorkSlice.ts` | Thunk + state for the response and the badge total. |
| `src/hooks/useMyWork.ts` | Fetch on mount and on route change. No polling. |
| `src/components/dashboard/StatTile.tsx` | One dashboard tile: label, count, link. |

**Frontend — modified**

| File | Change |
|---|---|
| `src/pages/Dashboard.tsx` | Placeholder → four tiles, Coming up, Needs attention. |
| `src/components/navConfig.tsx` | *My work* item with `badge: 'my-work'` (PR 1 deliberately left this out). |
| `src/components/NavDrawer.tsx` | Render the badge. |
| `src/App.tsx` | `/my-work` route. |
| `src/components/layout/routeMeta.ts` | `/my-work` entry (PR 2's new coverage guard will otherwise fail). |

**Deliberately NOT in this PR:** the `DataTable` migration and `DataGrid` lint rule (PR 4); the 1024px pass (PR 5); any change to the five worklists themselves — they already read their filters from the URL, which is the whole reason "View all →" needs no worklist change.

---

## Task 1: `GET /bookings` range filters

**Files:**
- Modify: `app/api/v1/bookings.py` (query params, beside `project_id` ~line 204), `app/services/booking_service.py` (`list_bookings`)
- Test: `tests/test_bookings_range_filter.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `GET /bookings?start=<iso>&end=<iso>`. Task 6's dashboard tile is its only planned consumer, but the filter is general.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bookings_range_filter.py
import pytest
from datetime import datetime, timedelta, timezone

from tests.factories import ensure_environment, make_booking


@pytest.mark.asyncio
async def test_a_booking_spanning_the_range_matches_even_though_it_started_before(
    client, auth_headers, test_tenant, db_session
):
    """The whole point of an OVERLAP test rather than a "starts within" one.

    A booking running 1-10 September is live on the 4th. An implementation of
    `start_date >= :start` passes every test that only seeds bookings starting
    inside the window, and is wrong for exactly the rows this filter exists to
    find.
    """
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    spanning = await make_booking(
        db_session,
        test_tenant.id,
        booked_by=current_user.id,
        environment=env,
        start=now - timedelta(days=3),
        end=now + timedelta(days=6),
    )
    before = await make_booking(
        db_session, test_tenant.id, booked_by=current_user.id, environment=env,
        start=now - timedelta(days=30), end=now - timedelta(days=20),
    )
    after = await make_booking(
        db_session, test_tenant.id, booked_by=current_user.id, environment=env,
        start=now + timedelta(days=20), end=now + timedelta(days=30),
    )

    r = await client.get(
        f"/api/v1/bookings/?start={now.isoformat()}&end={now.isoformat()}",
        headers=auth_headers,
    )
    assert r.status_code == 200
    ids = {row["id"] for row in r.json()}
    assert spanning.id in ids, "a booking spanning the probe instant is live now"
    assert before.id not in ids
    assert after.id not in ids


@pytest.mark.asyncio
async def test_a_zero_width_probe_is_what_the_live_now_tile_sends(
    client, auth_headers, test_tenant, db_session
):
    """`?start=<now>&end=<now>`. If overlap is written as a strict
    `start < :end AND end > :start` with no allowance, an empty probe range
    matches NOTHING and the dashboard tile silently reads zero."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    live = await make_booking(
        db_session, test_tenant.id, booked_by=current_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    r = await client.get(
        f"/api/v1/bookings/?start={now.isoformat()}&end={now.isoformat()}",
        headers=auth_headers,
    )
    assert live.id in {row["id"] for row in r.json()}


@pytest.mark.asyncio
async def test_the_range_filter_runs_in_sql_before_the_page(
    client, auth_headers, test_tenant, db_session
):
    """X-Total-Count must describe the FILTERED set. If the filter ran in
    Python after the query, the header would count the unfiltered rows and
    every paged consumer would be wrong."""
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    env = await ensure_environment(db_session, test_tenant.id)
    for i in range(3):
        await make_booking(
            db_session, test_tenant.id, booked_by=current_user.id, environment=env,
            start=now - timedelta(days=100 + i), end=now - timedelta(days=90 + i),
        )
    await make_booking(
        db_session, test_tenant.id, booked_by=current_user.id, environment=env,
        start=now - timedelta(hours=1), end=now + timedelta(hours=1),
    )
    r = await client.get(
        f"/api/v1/bookings/?start={now.isoformat()}&end={now.isoformat()}&limit=1",
        headers=auth_headers,
    )
    assert r.headers["X-Total-Count"] == "1"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_bookings_range_filter.py -q`
Expected: FAIL — `start`/`end` are unknown params today, so FastAPI ignores them and all four bookings come back. (That silent ignoring is exactly the trap this task exists to close.)

- [ ] **Step 3: Add the query params**

In `app/api/v1/bookings.py`'s list endpoint, beside the other filters:

```python
    start: Optional[datetime] = Query(
        None,
        description="Overlap window start. With `end`, returns bookings whose "
        "own interval overlaps it — NOT bookings that start inside it.",
    ),
    end: Optional[datetime] = Query(None, description="Overlap window end."),
```

Pass both to `booking_service.list_bookings`. If exactly one is supplied, that is a **422** — a half-specified range is far more likely a caller bug than an intent, and silently ignoring it is the failure this task is closing.

- [ ] **Step 4: Add the SQL clause**

In `booking_service.list_bookings`, filtered in SQL before pagination:

```python
    if start is not None and end is not None:
        # Interval overlap, decomposed rather than using GREATEST/LEAST —
        # SQLite has neither (see contention_forecast_service.overlapping_pairs).
        # `<=` on both sides, not `<`, so a zero-width probe (start == end,
        # which is what the "live now" tile sends) still matches a booking
        # spanning that instant.
        query = query.where(Booking.start_date <= end, Booking.end_date >= start)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest tests/test_bookings_range_filter.py -q`
Expected: PASS, 3 tests.

- [ ] **Step 6: Prove the overlap test discriminates**

Temporarily change the clause to `Booking.start_date >= start`. Expected: the spanning-booking test goes RED. Restore it and confirm GREEN. Report both runs — this is the mutation that separates a real overlap filter from the wrong one that passes a naive test suite.

- [ ] **Step 7: Run the floor and commit**

```bash
cd backend && uv run pytest -q
git add backend/app/api/v1/bookings.py backend/app/services/booking_service.py backend/tests/test_bookings_range_filter.py
git commit -m "feat(bookings): filter by overlapping date range"
```

---

## Task 2: Decommission membership narrowing + a public actionable clause

**Files:**
- Modify: `app/services/environment_decommission_service.py:820` (`worklist_query`), `app/services/environment_request_service.py:416` (rename) and its existing caller in `app/api/v1/environment_requests.py:64`
- Test: `tests/test_decommission_membership_narrowing.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `environment_decommission_service.worklist_query(tenant_id, *, now, sort=None, state=None, member_user_id=None)` — when `member_user_id` is given, restricted to decommissions whose environment's `operations_group_id` has that user as a member.
  - `environment_request_service.actionable_clause(tenant_id, user_id, is_admin)` — the same function, public.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_decommission_membership_narrowing.py
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_narrowing_returns_only_environments_whose_ops_group_i_am_in(
    db_session, test_tenant, current_user
):
    """Build the fixtures with this repo's factories; do NOT point a row at an
    id you did not create (SQLite ignored FKs until PRAGMA foreign_keys=ON and
    ~40 tests were inserting broken rows)."""
    me = await ensure_user(db_session, test_tenant.id, username='queue-member')
    mine_group = await ensure_user_group(db_session, test_tenant.id, name='Mine', members=[me])
    theirs_group = await ensure_user_group(db_session, test_tenant.id, name='Theirs', members=[])

    mine_env = await ensure_environment(db_session, test_tenant.id, operations_group_id=mine_group.id)
    theirs_env = await ensure_environment(db_session, test_tenant.id, operations_group_id=theirs_group.id)
    orphan_env = await ensure_environment(db_session, test_tenant.id, operations_group_id=None)

    mine = await make_decommission(environment_id=mine_env.id, tenant_id=test_tenant.id)
    theirs = await make_decommission(environment_id=theirs_env.id, tenant_id=test_tenant.id)
    orphan = await make_decommission(environment_id=orphan_env.id, tenant_id=test_tenant.id)

    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now, member_user_id=me.id)
    ids = {row.id for row in (await db_session.execute(q)).scalars()}
    assert mine.id in ids
    assert theirs.id not in ids
    assert orphan.id not in ids, (
        "an environment with NO operations group is nobody's queue — it must "
        "not fall through into everyone's"
    )


@pytest.mark.asyncio
async def test_without_the_parameter_nothing_changes(
    db_session, test_tenant
):
    """`/decommissions` is the estate-wide worklist and must be unaffected."""
    env = await ensure_environment(db_session, test_tenant.id, operations_group_id=None)
    d = await make_decommission(environment_id=env.id, tenant_id=test_tenant.id)
    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now)
    assert d.id in {row.id for row in (await db_session.execute(q)).scalars()}


@pytest.mark.asyncio
async def test_an_admin_is_narrowed_too(
    db_session, test_tenant, current_user
):
    """§5's "(Admin: all)" was struck. /my-work is a PERSONAL queue and follows
    `environment_request_service.actionable_clause`'s recorded reasoning: the
    Admin group-bypass exists so a transition is never impossible, and is not a
    claim about whose queue a row belongs in. An Admin in no group sees none.
    """
    admin = await ensure_user(db_session, test_tenant.id, username='queue-admin', role='Admin')
    other_group = await ensure_user_group(db_session, test_tenant.id, name='Other', members=[])
    env = await ensure_environment(db_session, test_tenant.id, operations_group_id=other_group.id)
    await make_decommission(environment_id=env.id, tenant_id=test_tenant.id)

    now = datetime.now(timezone.utc)
    from app.services import environment_decommission_service as svc

    q = svc.worklist_query(test_tenant.id, now=now, member_user_id=admin.id)
    assert (await db_session.execute(q)).scalars().all() == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_decommission_membership_narrowing.py -q`
Expected: FAIL — `worklist_query() got an unexpected keyword argument 'member_user_id'`.

**Before Step 3, check `ensure_user_group`'s real signature.** If it does not
take `members=`, add membership rows explicitly rather than inventing a kwarg —
and say so in your report, because the tests above assume it.

- [ ] **Step 3: Add the narrowing**

In `worklist_query`, mirroring how `environment_request_service.actionable_clause` builds its `member_exists`:

```python
    if member_user_id is not None:
        # The THIRD reader of group membership, after the two B3b established
        # (environment_request_service.assert_may_transition and
        # environment_service.assert_may_edit_handover). Same tenant scoping.
        # NO Admin bypass: this narrows a PERSONAL queue, and the bypass exists
        # so a transition is never impossible, not to decide whose queue a row
        # is in — see actionable_clause's docstring.
        member_exists = (
            select(UserGroupMember.id)
            .where(
                UserGroupMember.group_id == Environment.operations_group_id,
                UserGroupMember.user_id == member_user_id,
                UserGroupMember.tenant_id == tenant_id,
            )
            .exists()
        )
        query = query.where(member_exists)
```

An environment with a NULL `operations_group_id` joins against nothing and is therefore excluded — which is the intended answer, and the same degradation B3b documented.

- [ ] **Step 4: Rename the actionable clause**

`_actionable_clause` → `actionable_clause` in `environment_request_service.py`, and update its caller in `app/api/v1/environment_requests.py:64`. Add to its docstring: "Public because `my_work_service` is its second caller; a private reach-in from another service is how a predicate acquires a second definition."

```bash
grep -rn "_actionable_clause" backend/  # must return only the definition and its two callers
```

- [ ] **Step 5: Run the tests, then the floor**

Run: `cd backend && uv run pytest tests/test_decommission_membership_narrowing.py -q` → PASS, 3 tests.
Then: `cd backend && uv run pytest -q` → all green (the rename touches an existing endpoint).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/environment_decommission_service.py backend/app/services/environment_request_service.py backend/app/api/v1/environment_requests.py backend/tests/test_decommission_membership_narrowing.py
git commit -m "feat(decommissions): optional membership narrowing; make the actionable clause public"
```

---

## Task 3: `my_work_service` — the five queues under one clock

**Files:**
- Create: `app/services/my_work_service.py`, `app/schemas/my_work.py`
- Test: `tests/test_my_work_service.py` (create)

**Interfaces:**
- Consumes: Task 2's `worklist_query(..., member_user_id=)` and `actionable_clause`; the existing `contention_service.worklist_query`, `pir_finding_service.worklist_query`.
- Produces: `async def build(db, *, tenant_id: int, user: User, now: datetime) -> MyWorkResponse`, and these schemas:

```python
# app/schemas/my_work.py
class WorkItem(BaseModel):
    id: int
    title: str            # a NAME, never "#42" — see the display-names rule
    subtitle: str | None = None
    url: str              # the detail route this row opens
    due: datetime | None = None

class QueueResult(BaseModel):
    count: int
    items: list[WorkItem]
    overdue: int | None = None   # pir_actions only
    failed: bool = False         # true => the queue could not be computed

class MyWorkResponse(BaseModel):
    as_of: datetime
    queues: dict[str, QueueResult]   # keys: environment_requests, contentions,
                                     # decommissions, pir_actions, incidents
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_my_work_service.py
import pytest
from datetime import datetime, timezone
from unittest.mock import patch


@pytest.mark.asyncio
async def test_one_failing_queue_does_not_fail_the_response(
    db_session, test_tenant, current_user
):
    """§5: a dashboard that goes blank because one worklist is unhappy is worse
    than one showing four of five and saying so. `failed` is NOT the same as
    an empty queue — the card must never render "nothing waiting on you" for a
    queue that could not be computed."""
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    with patch(
        "app.services.my_work_service._incidents_queue",
        side_effect=RuntimeError("boom"),
    ):
        res = await my_work_service.build(
            db_session, tenant_id=test_tenant.id, user=user, now=now
        )

    assert set(res.queues) == {
        "environment_requests", "contentions", "decommissions",
        "pir_actions", "incidents",
    }
    assert res.queues["incidents"].failed is True
    assert res.queues["incidents"].count == 0
    assert res.queues["incidents"].items == []
    assert all(not q.failed for k, q in res.queues.items() if k != "incidents")


@pytest.mark.asyncio
async def test_every_queue_sees_the_same_instant(db_session, test_tenant, current_user):
    """One clock. Two datetime.now() calls in one response can disagree across
    midnight, and `expiry_boundary` turns that into two different answers about
    what is overdue."""
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    fixed = datetime(2026, 9, 4, 23, 59, 59, tzinfo=timezone.utc)
    from app.services import my_work_service

    with patch("app.services.my_work_service.datetime") as dt:
        dt.now.side_effect = AssertionError(
            "my_work_service must take no clock of its own; `now` is passed in"
        )
        res = await my_work_service.build(
            db_session, tenant_id=test_tenant.id, user=user, now=fixed
        )
    assert res.as_of == fixed


@pytest.mark.asyncio
async def test_items_carry_names_not_ids(
    db_session, test_tenant, current_user
):
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    await make_incident(tenant_id=test_tenant.id, title="Payments outage", status="open")
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=user, now=now
    )
    titles = [i.title for i in res.queues["incidents"].items]
    assert "Payments outage" in titles
    assert not any(t.startswith("#") for t in titles)


@pytest.mark.asyncio
async def test_each_queue_returns_at_most_five_items_but_counts_them_all(
    db_session, test_tenant, current_user
):
    user = await ensure_user(db_session, test_tenant.id, username='my-work-user')
    for i in range(8):
        await make_incident(tenant_id=test_tenant.id, title=f"Incident {i}", status="open")
    now = datetime.now(timezone.utc)
    from app.services import my_work_service

    res = await my_work_service.build(
        db_session, tenant_id=test_tenant.id, user=user, now=now
    )
    assert res.queues["incidents"].count == 8
    assert len(res.queues["incidents"].items) == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_my_work_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.my_work_service`.

- [ ] **Step 3: Write the schemas**

Exactly as in the Interfaces block above, in `app/schemas/my_work.py`.

- [ ] **Step 4: Write the service**

One private coroutine per queue (`_environment_requests_queue`, `_contentions_queue`, `_decommissions_queue`, `_pir_actions_queue`, `_incidents_queue`), each taking `(db, tenant_id, user, now)` and returning a `QueueResult`. Each calls its existing seam — **no new `select()` that restates a filter**. `build` runs them and wraps each in its own `try/except Exception`, logging and returning `QueueResult(count=0, items=[], failed=True)` on failure:

```python
async def build(db, *, tenant_id: int, user: User, now: datetime) -> MyWorkResponse:
    """`now` is passed IN, never taken here — one clock per request (§5)."""
    builders = {
        "environment_requests": _environment_requests_queue,
        "contentions": _contentions_queue,
        "decommissions": _decommissions_queue,
        "pir_actions": _pir_actions_queue,
        "incidents": _incidents_queue,
    }
    queues: dict[str, QueueResult] = {}
    for key, fn in builders.items():
        try:
            queues[key] = await fn(db, tenant_id=tenant_id, user=user, now=now)
        except Exception:
            logger.exception("my_work queue %s failed", key)
            queues[key] = QueueResult(count=0, items=[], failed=True)
    return MyWorkResponse(as_of=now, queues=queues)
```

Ordering within a queue is **soonest deadline, then oldest** (§5). Items are capped at five; `count` is the full count, from the same query.

- [ ] **Step 5: Run the tests** → PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/my_work_service.py backend/app/schemas/my_work.py backend/tests/test_my_work_service.py
git commit -m "feat(me): my_work_service composes five queues under one clock"
```

---

## Task 4: `GET /api/v1/me/work` + the count-equivalence guard

**Files:**
- Create: `app/api/v1/me.py`, `tests/test_me_work_matches_worklists.py`
- Modify: `app/main.py` (~line 94 imports, ~line 139 include_router)

**Interfaces:**
- Consumes: Task 3's `my_work_service.build`.
- Produces: `GET /api/v1/me/work` (JWT), returning `MyWorkResponse`.

- [ ] **Step 1: Write the failing test** — this is §9's guard, the one that gives "no restated predicates" teeth

```python
# tests/test_me_work_matches_worklists.py
import pytest
from datetime import datetime, timezone

# For each queue: seed rows on BOTH sides of the filter, then assert
# /me/work's count equals the worklist's X-Total-Count under the SAME filter.
# Seeding only matching rows would let a broken filter (or none at all) pass.

@pytest.mark.asyncio
async def test_incidents_count_matches_the_worklist(
    client, auth_headers, test_tenant, db_session
):
    for i in range(3):
        await make_incident(tenant_id=test_tenant.id, title=f"open {i}", status="open")
    for i in range(2):
        await make_incident(tenant_id=test_tenant.id, title=f"closed {i}", status="closed")

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get("/api/v1/incidents/?status=open&limit=1", headers=auth_headers)

    assert mine.status_code == 200
    assert mine.json()["queues"]["incidents"]["count"] == int(
        worklist.headers["X-Total-Count"]
    )
    assert mine.json()["queues"]["incidents"]["count"] == 3


@pytest.mark.asyncio
async def test_pir_actions_count_matches_and_a_due_today_action_is_not_overdue(
    client, auth_headers, test_tenant, db_session, current_user
):
    """The day-not-instant rule: `expiry_boundary` means an action due TODAY is
    not yet overdue. Asserting it here pins the shared clock as well as the
    count."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    await make_pir_action(tenant_id=test_tenant.id, owner_id=current_user.id,
                          status="open", due_date=today)
    await make_pir_action(tenant_id=test_tenant.id, owner_id=current_user.id,
                          status="done", due_date=today)

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    worklist = await client.get(
        f"/api/v1/pir-actions?owner_id={current_user.id}&status=open&limit=1",
        headers=auth_headers,
    )
    q = mine.json()["queues"]["pir_actions"]
    assert q["count"] == int(worklist.headers["X-Total-Count"]) == 1
    assert q["overdue"] == 0, "due today is not overdue"


@pytest.mark.asyncio
async def test_a_decommission_due_today_is_warned_not_due(
    client, auth_headers, test_tenant, db_session, current_user
):
    """B5's rule, restated at this seam because /me/work is a second reader of
    that state machine."""
    group = await ensure_user_group(db_session, test_tenant.id, name='Ops', members=[current_user])
    env = await ensure_environment(db_session, test_tenant.id, operations_group_id=group.id)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    await make_decommission(environment_id=env.id, tenant_id=test_tenant.id,
                            scheduled_teardown_at=today)

    mine = await client.get("/api/v1/me/work", headers=auth_headers)
    assert mine.json()["queues"]["decommissions"]["count"] == 1
```

Write the same shape for `environment_requests` (against `?actionable=true`) and `contentions` (against `?state=open&owner_user_id=<me>`).

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/test_me_work_matches_worklists.py -q`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 3: Write the route**

```python
# app/api/v1/me.py
router = APIRouter(prefix="/me", tags=["me"])


@router.get("/work", response_model=MyWorkResponse)
async def my_work(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ONE clock, taken here and threaded through every queue.
    now = datetime.now(timezone.utc)
    return await my_work_service.build(
        db,
        tenant_id=current_user.active_tenant_id,  # NOT .tenant_id — impersonation
        user=current_user,
        now=now,
    )
```

Register it in `app/main.py` beside the other routers.

- [ ] **Step 4: Run the tests** → PASS, 5 tests.

- [ ] **Step 5: Prove the equivalence test discriminates**

Temporarily change one queue's builder to return `QueueResult(count=0, items=[])`. Expected: that queue's equivalence test goes RED while the others stay green. Restore. Report both runs — a count test that passes against a hardcoded zero is worthless.

- [ ] **Step 6: Run BOTH backend legs and commit**

```bash
cd backend && uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q   # run ALONE
git add backend/app/api/v1/me.py backend/app/main.py backend/tests/test_me_work_matches_worklists.py
git commit -m "feat(me): GET /me/work returns the five queues in one round trip"
```

---

## Task 5: The `/my-work` page

**Files:**
- Create: `src/services/myWorkService.ts`, `src/store/myWorkSlice.ts`, `src/hooks/useMyWork.ts`, `src/components/mywork/QueueCard.tsx`, `src/pages/MyWork.tsx`, `src/pages/__tests__/myWork.test.tsx`
- Modify: `src/App.tsx` (route), `src/components/layout/routeMeta.ts` (entry — PR 2's coverage guard fails without it), `src/store/index.ts` (reducer)

**Interfaces:**
- Consumes: `GET /me/work` (Task 4).
- Produces: `useMyWork()` returning `{ data, loading, error, total }`; `myWorkSlice` holding the response and the badge total for Task 7.

- [ ] **Step 1: Write the failing test**

```tsx
// src/pages/__tests__/myWork.test.tsx
describe('MyWork', () => {
  it('renders a card for every queue, including empty ones', async () => {
    // §5: "cards are never hidden" — a hidden card is indistinguishable from
    // a queue you are not a member of.
    renderWithStore(<MyWork />, { queues: { ...allFive, contentions: { count: 0, items: [] } } });
    expect(await screen.findByRole('heading', { name: /contentions/i })).toBeInTheDocument();
    expect(screen.getByText('Nothing waiting on you')).toBeInTheDocument();
  });

  it('a FAILED queue is not rendered as an empty one', async () => {
    // The distinction this whole degradation design exists for.
    renderWithStore(<MyWork />, {
      queues: { ...allFive, incidents: { count: 0, items: [], failed: true } },
    });
    expect(await screen.findByText(/couldn't load/i)).toBeInTheDocument();
    expect(screen.queryByText('Nothing waiting on you')).not.toBeInTheDocument();
  });

  it('View all links to the worklist with the same filter in the URL', async () => {
    renderWithStore(<MyWork />, { queues: allFive });
    const link = await screen.findByRole('link', { name: /view all incidents/i });
    expect(link).toHaveAttribute('href', '/incidents?status=open');
  });

  it('shows at most five rows even when the count is higher', async () => {
    renderWithStore(<MyWork />, {
      queues: { ...allFive, incidents: { count: 12, items: fiveItems } },
    });
    expect(await screen.findAllByTestId('queue-row')).toHaveLength(5);
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails** → module not found.

- [ ] **Step 3: Build the service, slice and hook**

`myWorkService.ts` is a thin `api.get('/me/work')`. The slice's thunk uses `rejectWithValue(formatApiError(err))` — **not** `result.error.message`, which RTK's `miniSerializeError` reduces to "Request failed with status code 500", losing the server's `detail`.

- [ ] **Step 4: Build `QueueCard` and the page**

`QueueCard` takes `{ title, queue, viewAllHref, renderRow }`. Three states: rows, "Nothing waiting on you", and the failed state with a retry. `MyWork.tsx` composes five of them and uses `PageHeader` from PR 2.

- [ ] **Step 5: Add the route and the routeMeta entry**

`/my-work` in `App.tsx` inside the `AppLayout` block, and `ROUTE_META['/my-work'] = { label: 'My work' }`. PR 2's route-coverage guard fails if the entry is missing — that guard exists precisely to catch this.

- [ ] **Step 6: Run the tests, gate, commit**

```bash
npx vitest run src/pages src/hooks src/__tests__
npx tsc --noEmit && npm run lint
git commit -m "feat(my-work): the /my-work inbox"
```

---

## Task 6: The dashboard

**Files:**
- Create: `src/components/dashboard/StatTile.tsx`, `src/pages/__tests__/dashboard.test.tsx`
- Modify: `src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: Task 1's `?start=&end=` for the "Bookings live now" tile; PR 2's `PageHeader`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing test**

```tsx
describe('Dashboard', () => {
  it('reads each tile count from X-Total-Count, not from the row array', async () => {
    // The tiles fetch limit=1; a tile that counted `data.length` would show 1.
    mockGet('/environments', { data: [oneRow], headers: { 'x-total-count': '42' } });
    render(<Dashboard />);
    expect(await screen.findByText('42')).toBeInTheDocument();
  });

  it('each tile links to the list with the same filter', async () => {
    render(<Dashboard />);
    expect(await screen.findByRole('link', { name: /active environments/i }))
      .toHaveAttribute('href', '/environments?status=active');
  });

  it('renders no Phase-0 placeholder text', async () => {
    render(<Dashboard />);
    expect(screen.queryByText(/Phase 0/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails.**

- [ ] **Step 3: Build `StatTile` and rewrite `Dashboard`**

Four tiles (`?status=active` environments; bookings `?start=<now>&end=<now>`; releases in flight; `?status=open` incidents), each a `limit=1` fetch reading `X-Total-Count`. Then "Coming up" from the calendar range endpoints, and "Needs attention" reusing `<ContentionHorizon />` (it takes no props) and the health alert banner unchanged, plus the Admin-only governance-gap/quarantined line.

- [ ] **Step 4: Run the tests, gate, commit.**

---

## Task 7: The nav badge

**Files:**
- Modify: `src/components/navConfig.tsx` (the *My work* item with `badge: 'my-work'`), `src/components/NavDrawer.tsx` (render it), `src/components/AppLayout.tsx` (call `useMyWork` on route change)
- Test: `src/components/__tests__/navBadge.test.tsx` (create)

**Interfaces:** Consumes Task 5's `useMyWork`.

- [ ] **Step 1: Write the failing test**

```tsx
it('shows the sum of the five counts', async () => { /* 2+0+1+3+4 => 10 */ });
it('renders no badge when every queue is empty', async () => { /* not a "0" */ });
it('refetches on route change, and does not poll', async () => {
  // §5: "fetched on mount and on every route change ... No polling."
  // Assert the fetch count after a navigation, and that advancing timers
  // by a minute adds none.
});
```

- [ ] **Step 2-4:** run RED, implement, run GREEN, gate, commit.

---

## Task 8: Whole-suite run, browser pass, docs

- [ ] **Step 1: Three runs.** `cd backend && uv run pytest -q`; then the PostgreSQL leg **alone**; then `cd frontend && npx vitest run`. All green before proceeding.

- [ ] **Step 2: Build and gate.** `npx tsc --noEmit && npm run lint && npm run build`.

- [ ] **Step 3: Browser pass**, recorded in the PR description. **Restart the dev server first** (`npm run dev`) — a long-running one serves stale optimised deps and produces errors that look exactly like app bugs. In both light and dark:

1. `/my-work` — five cards; at least one with rows, one empty saying "Nothing waiting on you".
2. Stop the backend, reload `/my-work` — cards show the failed state, **not** "Nothing waiting on you". Restart it.
3. "View all →" on a non-empty card lands on the worklist **with the filter applied** — check the row count matches the card's count.
4. The nav badge equals the sum of the five counts, and changes after actioning an item and navigating.
5. `/dashboard` — four tiles with counts; each links to its filtered list; the "Bookings live now" tile matches what `/bookings` shows for the same instant.
6. Breadcrumbs and `document.title` on both new pages.

- [ ] **Step 4: Docs.** `docs/user-guide.md` §2 gains My work and the dashboard (§10 of the spec: docs move in the same PR). `docs/ui-audit.md` — mark anything this PR closes.

- [ ] **Step 5: Commit and open the PR** with the browser pass recorded.

---

## Appendix A: factories these tests need, and which do not exist yet

`backend/tests/factories.py` provides `ensure_user`, `ensure_user_group`,
`ensure_environment`, `ensure_environment_tier`, `ensure_project`,
`ensure_environment_group`, `ensure_environment_request`, `ensure_build`,
`ensure_change_request`, `ensure_deployment`, `ensure_subsystem`,
`ensure_booking_type` and `make_booking`. Note the two prefixes are a
convention, not decoration: `ensure_` is idempotent, `make_` always creates a
new row.

**Three helpers these tests need DO NOT EXIST and must be added to
`tests/factories.py` by the first task that needs one** — Task 2 needs
`make_decommission`, Tasks 3-4 need `make_incident` and `make_pir_action`:

- Follow the file's existing shape (async, `db: AsyncSession` first, tenant id
  second, keyword-only the rest, `await db.flush()` not `commit()`).
- **Never point a row at an id you did not create.** SQLite silently ignored
  foreign keys until `PRAGMA foreign_keys=ON` was added and ~40 tests were
  inserting broken rows and passing. A `make_decommission` must create or take
  a real `Environment`, not accept a bare `environment_id=1`.
- Add them in the same commit as the task that first needs them, not as a
  separate "test infrastructure" commit — a factory with no caller is the
  connected-to-nothing class this repo has shipped four times.

`current_user` and `test_tenant` are existing conftest fixtures. **Do not mix
the `tenant` fixture with `auth_headers`** — `tenant` creates a *different*
tenant ("Phase3 Org") from the one `auth_headers` authenticates into, so a
test combining them queries across two tenants and can pass vacuously.

## Appendix B: what this plan deliberately does not do

- **No new aggregation endpoint for the dashboard.** Tiles read `X-Total-Count` from `limit=1` fetches of the existing list endpoints. Inventing `/dashboard/summary` would create a second place that decides what "active" means.
- **No worklist changes.** Every worklist already reads its filters from search params, which is exactly why "View all →" can hand it the same filter in a URL.
- **No polling and no notifications** (§11). The badge is fetched on navigation; a user who never navigates sees a stale count, which is acceptable for an inbox and avoids a standing load per open tab.
