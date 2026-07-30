# Pagination Sub-project C1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the bounded list endpoints whitelisted server-side sorting, and add the five filter parameters the grids need and the endpoints lack.

**Architecture:** A `sorting()` factory beside `pagination()` resolves `sort_by`/`sort_dir` against a per-endpoint whitelist and returns a `Sort`. Services apply it *before* their existing primary-key tiebreaker, so ordering stays total. Filters are added as ordinary SQL predicates matching what the browser does today.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, PostgreSQL + SQLite, pytest / pytest-asyncio 1.4.0, `uv`.

Spec: [`docs/superpowers/specs/2026-07-30-pagination-sweep-c1-design.md`](../specs/2026-07-30-pagination-sweep-c1-design.md)
Branch: `feature/pagination-sweep-c1`, off `feature/pagination-sweep-b` (PR #37 → PR #36 → main).

## Global Constraints

- **Nothing may change until C3 lands.** C1 adds only *optional* parameters. Every endpoint's default ordering and unfiltered results must be byte-identical afterwards. Each task proves this with a default-ordering test; it is what makes C1 safe to merge ahead of the frontend.
- **The whitelist is the security boundary.** `sort_by` is a client-supplied string. It is looked up in a mapping and a miss is a **422**. No `getattr`, no string interpolation into SQL, no silent fallback to a default — a client told nothing while receiving a different order than it asked for is worse off than one given an error.
- **Sorting composes with the tiebreaker; it never replaces it.** The applied ordering is *requested sort, then the endpoint's existing unique tiebreaker*. Sub-project A demonstrated empirically that dropping a tiebreaker breaks pagination deterministically on PostgreSQL — a sort column is almost never unique, so this is exactly the situation that bug lives in.
- **Only sort by what SQL can sort.** Columns computed in Python after the page is fetched (`phase_count`, `pir_status`, `latest_step`, `conflicts`, …) are not whitelisted. C3 sets `sortable: false` on them.
- Services take `page: Optional[Page] = None` and now `sort: Optional[Sort] = None`, returning `(rows, total)`. Both default to `None`, so non-request callers are unaffected.
- No `db.commit()` in services. Tenant-scoped queries filter by `tenant_id`; endpoints use `current_user.active_tenant_id`.
- **Never fabricate a foreign key id in a test** — use `backend/tests/factories.py`.
- `request.getfixturevalue` does not work on async fixtures under pytest-asyncio 1.4.0 — pass fixtures as normal parameters.
- **Hold strong references to rows created in tests.** SQLAlchemy's identity map can drop an object after `flush()`, and re-materialising from SQLite loses `tzinfo` on `DateTime(timezone=True)` columns. This bit sub-project B twice.
- **Verification cadence.** Targeted tests on SQLite per task; full dual-engine at two checkpoints (after Task 1, and Task 10). Full suite is ~6 min SQLite / ~15 min PostgreSQL. **Only one agent may use `envmgr_test` at a time — concurrent PostgreSQL runs deadlock it.** **Never background a test run.**
- Run all commands from `backend/`.

## Verified facts — read from the code, do not re-derive

| Endpoint | Current default ordering (must be preserved) | Bounded today |
|---|---|---|
| `GET /releases` | `Release.created_at.desc(), Release.id` | ✅ 50/200 |
| `GET /bookings/` | `Booking.start_date.asc(), Booking.id` | ✅ 1000 |
| `GET /environments/` | `Environment.name, Environment.id` | ✅ 1000 |
| `GET /change-requests` | `ChangeRequest.scheduled_start.desc(), ChangeRequest.id` | ✅ 1000 |
| `GET /systems/` | `System.name, System.id` | ✅ 1000 |
| `GET /infrastructure-components/` | `InfrastructureComponent.name, InfrastructureComponent.id` | ✅ 1000 |
| `GET /incidents` | `Incident.detected_at.desc(), Incident.id` | ✅ 1000 |
| `GET /deployments` | `Deployment.deployed_at.desc(), Deployment.id` | ✅ 100/500 |
| `GET /builds` | `Build.commit_timestamp.desc()` — **no tiebreaker** | ❌ own `limit=100/le=500`, no `set_total_count` |

Other facts:
- `/builds` and `/deployments` build their queries **inline in the endpoint**, not in a service. `/builds` already `outerjoin`s `SubSystem` and `Release` (`select(Build, SubSystem.name, Release.name)`), and `/deployments` already joins `Build`, `Environment`, `Release`, `ChangeRequest` via `_select_with_joins()`. Both joins are many-to-one on primary keys, so predicates on the joined columns cannot change row multiplicity.
- `infrastructure_component_service.list_infrastructure_components` already has a `search` parameter, matching `name` only (`InfrastructureComponent.name.ilike(f"%{search}%")`).
- `fetch_page` / `fetch_page_rows` live in `app/core/pagination.py` and take `(db, query, page)`.

## File Structure

| File | Change |
|---|---|
| `app/core/pagination.py` | Add `Sort`, `sorting()`, and `apply_sort()` |
| `app/services/{environment,system,incident,change_request,booking,release,infrastructure_component}_service.py` | Accept `sort`, apply before the tiebreaker; two gain a `search` filter |
| `app/api/v1/{environments,systems,incidents,change_requests,bookings,releases,infrastructure_components}.py` | Add `sort: Sort = Depends(sorting(...))` and pass through |
| `app/api/v1/deployments.py`, `app/api/v1/builds.py` | Same, inline; builds also gains bounding |
| `tests/test_sorting.py` | **new** — primitive, whitelist enforcement, per-endpoint order, tie-paging |
| `docs/pagination.md`, `CLAUDE.md` | Document sorting, the whitelists, and the capability loss |

---

## Task 1: The `sorting()` primitive

**Files:** Modify `app/core/pagination.py`; create `tests/test_sorting.py`.

**Interfaces produced:**
- `Sort` — frozen dataclass with `column: InstrumentedAttribute`, `descending: bool`
- `sorting(allowed: Mapping[str, InstrumentedAttribute], default: str) -> Callable[..., Sort]`
- `apply_sort(query: Select, sort: Optional[Sort]) -> Select`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_sorting.py`:

```python
"""Server-side sorting: the whitelist, and that it composes with the tiebreaker.

The whitelist is the security boundary — `sort_by` is a client string and must
never reach the query as a column name. And a sort column is almost never
unique, so the sort must PRECEDE the existing primary-key tiebreaker rather
than replace it; sub-project A showed that dropping a tiebreaker breaks paging
deterministically on PostgreSQL.
"""
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.pagination import Page, Sort, apply_sort, fetch_page, sorting
from app.db.models.environment import Environment

ALLOWED = {"name": Environment.name, "created_at": Environment.created_at}


def _probe_app():
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe(sort: Sort = Depends(sorting(ALLOWED, default="name"))):
        return {"column": str(sort.column.key), "descending": sort.descending}

    return probe


@pytest.mark.asyncio
async def test_default_is_used_when_no_sort_requested():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"column": "name", "descending": False}


@pytest.mark.asyncio
async def test_requested_field_and_direction_are_honoured():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        body = (await ac.get("/probe?sort_by=created_at&sort_dir=desc")).json()
        assert body == {"column": "created_at", "descending": True}


@pytest.mark.asyncio
async def test_unknown_field_is_422_not_a_silent_default():
    """A client that asked for a sort it did not get is worse off than one
    told its request was impossible."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe?sort_by=nonexistent")).status_code == 422


@pytest.mark.asyncio
async def test_injection_shaped_input_is_rejected_by_the_whitelist():
    """Not escaped downstream — rejected outright, because nothing interpolates."""
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        hostile = "name; DROP TABLE environment--"
        assert (await ac.get(f"/probe?sort_by={hostile}")).status_code == 422


@pytest.mark.asyncio
async def test_bad_direction_is_422():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe?sort_dir=sideways")).status_code == 422


# ── apply_sort composes with, and does not replace, the tiebreaker ───────────


@pytest.mark.asyncio
async def test_paging_a_sorted_query_over_ties_sees_each_row_once(db_session, test_tenant):
    """Every row shares a name, so the sort column alone leaves 25 ties. If
    apply_sort replaced the tiebreaker instead of preceding it, rows would
    duplicate and vanish across pages."""
    created = []
    for _ in range(25):
        env = Environment(
            tenant_id=test_tenant.id, name="identical", environment_type="SIT"
        )
        created.append(env)
        db_session.add(env)
    await db_session.flush()

    query = apply_sort(
        select(Environment).where(Environment.tenant_id == test_tenant.id),
        Sort(column=Environment.name, descending=False),
    ).order_by(Environment.id)

    seen, offset = [], 0
    while True:
        rows, total = await fetch_page(db_session, query, Page(limit=6, offset=offset))
        assert total == 25
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += 6

    assert len(seen) == 25
    assert len(set(seen)) == 25, "a row appeared on more than one page"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_sorting.py -q`
Expected: FAIL — `ImportError: cannot import name 'Sort' from 'app.core.pagination'`

- [ ] **Step 3: Implement the primitive**

Append to `app/core/pagination.py`:

```python
@dataclass(frozen=True)
class Sort:
    column: InstrumentedAttribute
    descending: bool


def sorting(
    allowed: Mapping[str, InstrumentedAttribute], default: str
) -> Callable[..., Sort]:
    """Build a FastAPI dependency resolving `sort_by`/`sort_dir` against a whitelist.

    `allowed` maps the client-facing field name to the column it sorts by. The
    mapping is the entire security boundary: `sort_by` is a client-supplied
    string and is looked up, never used to address a column. An unknown field is
    a 422 rather than a silent fallback — a client that receives a different
    order than it asked for, with no error, will render it as though it were the
    order it requested.

    The returned Sort is applied by `apply_sort` BEFORE the caller's existing
    tiebreaker. A sort column is almost never unique, so a sort that replaced the
    tiebreaker would reintroduce the duplicate/missing-row bug that LIMIT/OFFSET
    over a partial order produces.
    """
    if default not in allowed:
        raise ValueError(f"default sort {default!r} is not in the whitelist")

    field_names = sorted(allowed)

    def _sorting(
        sort_by: str = Query(
            default,
            description=f"Field to sort by. One of: {', '.join(field_names)}.",
        ),
        sort_dir: str = Query(
            "asc", pattern="^(asc|desc)$", description="Sort direction."
        ),
    ) -> Sort:
        column = allowed.get(sort_by)
        if column is None:
            raise HTTPException(
                status_code=422,
                detail=f"sort_by must be one of: {', '.join(field_names)}",
            )
        return Sort(column=column, descending=sort_dir == "desc")

    return _sorting


def apply_sort(query: Select, sort: Optional[Sort]) -> Select:
    """Order `query` by `sort`, if given.

    Chain the caller's unique tiebreaker after this — `apply_sort(q, s).order_by(Model.id)`.
    SQLAlchemy appends, so the tiebreaker stays the final key.
    """
    if sort is None:
        return query
    return query.order_by(sort.column.desc() if sort.descending else sort.column.asc())
```

Add imports: `from typing import Callable, Mapping, Optional`, `from fastapi import HTTPException, Query, Response`, `from sqlalchemy.orm.attributes import InstrumentedAttribute`.

Note the 422 is raised via `HTTPException`, not a Pydantic validation error, because the valid set is only known at dependency-construction time. Confirm FastAPI surfaces it as 422 in the probe test rather than 500.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_sorting.py -q`
Expected: PASS — 6 tests.

- [ ] **Step 5: CHECKPOINT — full dual-engine suite**

The primitive is imported by everything downstream, so verify before building on it.

Run: `cd backend && uv run pytest -q` — expect 969 passed, 1 skipped. Allow 8 minutes, foreground.
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` — allow 20 minutes, foreground.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/pagination.py backend/tests/test_sorting.py
git commit -m "feat(api): add a whitelist-based sorting primitive

sort_by is a client string, so it is looked up in a per-endpoint mapping and
never used to address a column; an unknown field is a 422 rather than a silent
fallback. apply_sort precedes the caller's tiebreaker rather than replacing it,
because a sort column is almost never unique."
```

---

## Tasks 2–7: apply sorting (and the missing filters) per endpoint

Each task follows the same five steps. They are separated so a reviewer can reject one endpoint's whitelist without rejecting the rest.

**The shared shape**, using environments as the worked example:

Service — add `sort` and apply it *before* the existing tiebreaker:

```python
async def list_environments(
    db, tenant_id, *, status_filter=None, environment_type=None,
    search: Optional[str] = None,
    page: Optional[Page] = None,
    sort: Optional[Sort] = None,
) -> tuple[list[Environment], int]:
    ...
    if search:
        query = query.where(Environment.name.ilike(f"%{search}%"))
    query = apply_sort(query, sort).order_by(Environment.name, Environment.id)
    return await fetch_page(db, query, page)
```

**Careful:** the existing ordering line is *replaced* by this form, not appended to. When `sort` is `None` the result is `.order_by(Environment.name, Environment.id)` — byte-identical to today. That equivalence is what the default-ordering test proves, and it is the whole reason C1 is safe to merge before C3.

Endpoint — add the dependency:

```python
    sort: Sort = Depends(sorting(ENVIRONMENT_SORTS, default="name")),
```
with the whitelist declared at module level:
```python
ENVIRONMENT_SORTS = {
    "name": Environment.name,
    "environment_type": Environment.environment_type,
    "status": Environment.status,
    "created_at": Environment.created_at,
}
```

**Per task, the five steps are:**

1. **Write the tests first and watch them fail** — three per endpoint:
   - *default unchanged*: with no `sort_by`, the returned order equals the order before this change (seed rows whose insertion order differs from the sorted order, and assert the exact id sequence);
   - *each sortable field, both directions*: seed rows whose sort column deliberately disagrees with insertion order, and assert the sequence — **seeding already-ordered rows proves nothing**, which is the defect found in sub-project B's first ordering test;
   - *unknown field is 422* through the real endpoint, not just the probe app.
2. Add the whitelist constant and the service `sort` parameter.
3. Add the endpoint dependency and pass `sort=sort` through.
4. Sweep callers (`grep -rn "<service_fn>(" app/ tests/ scripts/`) — the signature gains a keyword-only parameter with a default, so existing callers keep working, but confirm rather than assume.
5. Run targeted tests on SQLite; commit.

### Task 2 — environments + systems

Both order `name, id` today. Both also gain the **`search`** parameter (case-insensitive `name` contains) that their grids apply in the browser.

- `ENVIRONMENT_SORTS`: `name`, `environment_type`, `status`, `created_at`. Default `name`.
- `SYSTEM_SORTS`: `name`. Default `name`.

Add a filter-equivalence test for `search`: seed names that a case-insensitive contains would and would not match (including a differing-case match), and assert the SQL agrees.

### Task 3 — incidents + change-requests

- `INCIDENT_SORTS`: `title`, `severity`, `status`, `detected_at`, `resolved_at`. Default `detected_at`, **descending** — note the existing default is `detected_at DESC`, so the endpoint must pass `sort_dir` default accordingly or the whitelist default must encode direction. Simplest: keep `sorting(...)`'s `sort_dir` default `"asc"` and instead have the service's fallback ordering unchanged when `sort_by` is not supplied. **Read the resulting behaviour carefully** — the default-unchanged test is what proves you got it right.
- `CHANGE_REQUEST_SORTS`: `title`, `change_type`, `status`, `scheduled_start`. Default `scheduled_start` desc, same consideration.

### Task 4 — bookings + releases

- `BOOKING_SORTS`: `start_date`, `end_date`, `status`. Default `start_date` asc.
- `RELEASE_SORTS`: `name`, `release_type`, `release_kind`, `status`, `target_date`, `created_at`. Default `created_at` desc.

`releases` is the endpoint whose truncation motivated all of sub-project C — its default limit is 50. Do **not** change that limit here; C1 only adds parameters.

`release_service.list_releases` takes `limit`/`offset` rather than a `Page`; add `sort` alongside them and apply it before `Release.id`.

### Task 5 — infrastructure-components

- `INFRASTRUCTURE_SORTS`: `name`, `component_type`, `provider`, `region`, `source`. Default `name`.
- **Widen the existing `search`**: it currently matches `name` only; the grid searches name **or** provider **or** region. Change to `or_(name.ilike(q), provider.ilike(q), region.ilike(q))`. `provider` and `region` are nullable — confirm a NULL column does not exclude a row whose `name` matches (it will not, since `OR` with NULL still yields true when another operand is true, but assert it in a test).

### Task 6 — deployments

Inline in `app/api/v1/deployments.py`.

- `DEPLOYMENT_SORTS`: `status`, `deployer_name`, `deployed_at`. Default `deployed_at` desc.
- Add `environment_search` and `release_search`: `ilike` predicates on `Environment.name` and `Release.name`, both **already joined** by `_select_with_joins()`. The joins are many-to-one on primary keys, so adding predicates cannot change row multiplicity — but confirm the count is still right with a test that filters and checks `X-Total-Count`.

### Task 7 — builds

`/builds` is the only endpoint in this plan that is **not bounded at all**: it has its own `limit=Query(100, le=500)`, no `set_total_count`, and orders by `Build.commit_timestamp.desc()` with **no tiebreaker**. So this task does three things:

1. **Bound it** — convert to `Depends(pagination(default_limit=100, max_limit=500))`, preserving its contract, and add `set_total_count`. It selects `(Build, SubSystem.name, Release.name)`, so it needs **`fetch_page_rows`**, not `fetch_page`.
2. **Add the tiebreaker** — `Build.commit_timestamp.desc(), Build.id`.
3. **Add sort and search** — `BUILD_SORTS`: `git_branch`, `build_number`, `commit_timestamp`, default `commit_timestamp` desc; plus `subsystem_search` as an `ilike` on the already-outer-joined `SubSystem.name`.

Note `SubSystem` is joined with `outerjoin`, so a build with no subsystem has `NULL` there. Confirm `subsystem_search` excludes such rows (it will — `NULL ILIKE x` is NULL) and that this matches what the browser does today (`(b.subsystem_name ?? '').toLowerCase().includes(needle)` — an empty string contains only an empty needle, so a non-empty search excludes them; the behaviours agree, but assert it).

Also add `builds` to `BOUNDED_ENDPOINTS` in `tests/test_pagination.py` once it sets the header.

---

## Task 8: Sort-aware tie paging across every endpoint

**Files:** Modify `tests/test_sorting.py`.

Task 1 proved the primitive composes with a tiebreaker in isolation. This proves it for each real endpoint — the case where a sort silently replaced the tiebreaker rather than preceding it.

- [ ] **Step 1: Write a parametrised test**

For each endpoint with a whitelist, seed rows that **all tie on one sortable column**, page through the whole set with that `sort_by`, and assert every row appears exactly once. Use the `BOUNDED_ENDPOINTS`-style table so adding an endpoint later means adding a row.

- [ ] **Step 2: Prove it guards**

For at least two endpoints, temporarily change the service's ordering from `apply_sort(query, sort).order_by(Model.id)` to `apply_sort(query, sort)` — dropping the tiebreaker — confirm the test FAILS, restore, confirm it passes. Report both observations. **This must run on PostgreSQL**; SQLite's plans are stable enough to pass by luck.

- [ ] **Step 3: Commit**

---

## Task 9: Documentation

**Files:** `docs/pagination.md`, `CLAUDE.md`.

- [ ] **Step 1** — document the `sorting()` primitive beside `pagination()`: the whitelist as security boundary, 422 rather than silent fallback, and that `apply_sort` precedes the tiebreaker.
- [ ] **Step 2** — record each endpoint's whitelist and default. C3 takes this table as its input; it is the contract between the two halves.
- [ ] **Step 3** — **state the capability loss plainly**: columns computed in Python after the page is fetched cannot be sorted server-side, so once C3 lands users can no longer sort by them. They can today, but that sorts a truncated set. Name the affected columns.
- [ ] **Step 4** — record the new filter parameters and that each matches the browser's case-insensitive contains.
- [ ] **Step 5** — `/builds` is now bounded; move it out of the "own ad hoc limit" group and re-derive the counts with the documented command.
- [ ] **Step 6** — note the unenforced seam: nothing checks that C3's `sortable` flags match these whitelists.
- [ ] **Step 7** — update `CLAUDE.md`'s counts and add sorting to the "Unbounded list endpoints" pitfall entry.
- [ ] **Step 8** — verify every claim with `grep`; report what you checked.

---

## Task 10: Final verification and PR

- [ ] **Step 1** — full suite on both engines, foreground. Record both totals.
- [ ] **Step 2** — confirm **no endpoint's default behaviour changed**: for each of the nine, the default-ordering test exists and passes. This is the property that makes C1 mergeable before C3.
- [ ] **Step 3** — confirm no `sort_by` value can reach a query as a column name: grep for `getattr(`, f-strings and `text(` near the sort code.
- [ ] **Step 4** — push and open the PR with base **`feature/pagination-sweep-b`**, noting the stack order #36 → #37 → this.

---

## Self-Review

**Spec coverage.** Primitive → Task 1; whitelists → Tasks 2–7; the five missing filters → Tasks 2 (environments, systems), 5 (infrastructure), 6 (deployments), 7 (builds); tie-paging → Task 8; docs including the capability loss → Task 9; verification → Task 10.

**Known soft spots, stated rather than hidden:**

1. **Tasks 3 and 4 have a real ambiguity in how a descending default is expressed.** `sorting()`'s `sort_dir` defaults to `"asc"`, but four endpoints default to a descending order today. The plan flags this and makes the default-unchanged test the arbiter rather than prescribing a mechanism, because both plausible designs (encode direction in the whitelist default, or leave the service's fallback ordering untouched when `sort_by` is absent) have consequences I have not tested. The implementer must resolve it and say which it chose.
2. `HTTPException(422)` from inside a dependency is assumed to surface as 422 rather than 500. Task 1's probe test checks it directly, so this is verified before anything depends on it.
3. Task 7 changes `/builds` from unbounded to bounded — the only behaviour change in C1. Its default page size (100) matches its current hardcoded limit, so no page shrinks, but it is worth a reviewer's attention.
