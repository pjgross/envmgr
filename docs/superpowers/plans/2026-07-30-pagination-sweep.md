# Backend Pagination Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound the list endpoints that can be bounded mechanically, using the shared pagination primitive, without changing any client-visible behaviour.

**Architecture:** Two additions to `app/core/pagination.py` — a `pagination()` factory so endpoints with existing limit contracts keep them, and a `fetch_page_rows` sibling for multi-column selects. Every bounded endpoint then gains a `Page` dependency, a `set_total_count` call, and a primary-key tiebreaker on its ordering. Three endpoints with queries written inline move into services first.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, PostgreSQL + SQLite (dual-engine test suite), pytest / pytest-asyncio, `uv` for running tests.

Spec: [`docs/superpowers/specs/2026-07-30-pagination-sweep-design.md`](../specs/2026-07-30-pagination-sweep-design.md)

## Global Constraints

- **Backward compatible.** Endpoints keep returning a bare JSON array. The total goes only in the `X-Total-Count` header. No response body shape changes.
- **`DEFAULT_LIMIT = 500`, `MAX_LIMIT = 1000`** stay as they are. `GET /releases` keeps its 50/200 contract; `GET /deployments` keeps 100/500.
- **Total ordering is mandatory.** Every bounded endpoint's query ends with a unique tiebreaker (the primary key). `LIMIT`/`OFFSET` over a partial order returns duplicate and missing rows across pages.
- **Enrichment after the query is fine; filtering or merging after it is not.** If a service removes rows or concatenates two executed queries, it does not get a `Page` — it is out of scope (sub-project B).
- **Services** take `page: Optional[Page] = None` and return `(rows, total)`. `page=None` returns everything, so non-request callers are unaffected.
- **No `db.commit()` in services** — `get_db()` auto-commits. Use `db.flush()`.
- **Tenant scoping** — every query on a tenant-scoped table filters by `tenant_id`; endpoints use `current_user.active_tenant_id`, never `.tenant_id`.
- **Verification cadence** (revised after measuring — see below). Per task, run the **targeted** tests: the task's own test file plus the test modules covering the endpoints it touched, on SQLite. That is seconds. The **full dual-engine suite** runs at three checkpoints only: after Task 1, after Task 8, and at Task 14.

  Measured on this machine: the full suite is **923 passed, 1 skipped** in 5m50s on SQLite and 13m49s on PostgreSQL. Running both after each of 14 tasks would be ~4.7 hours, almost all of it re-executing 900 tests the change cannot reach. A targeted run of `tests/test_pagination.py` is 3.3 seconds.

  Commands — targeted: `cd backend && uv run pytest tests/test_pagination.py tests/<other affected> -q`. Full SQLite: `cd backend && uv run pytest -q`. Full PostgreSQL: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` — allow **20 minutes**, do not background it and poll.

  All fixture rows go through `tests/factories.py` — never fabricate a foreign key.
- **Working directory** for all commands is `backend/`. Branch is `feature/pagination-sweep`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/core/pagination.py` | The primitive: `Page`, `pagination()` factory, `fetch_page`, `fetch_page_rows`, `set_total_count` | Modify |
| `app/api/v1/{bookings,change_requests,infrastructure_components,environment_health,admin,tenant_admin,releases,deployments,conflicts,enterprise_rollup,booking_requests}.py` | Thin endpoints: add `Page` + `set_total_count` | Modify |
| `app/services/{booking,change_request,infrastructure_component,environment_health,tenant,user_admin,release_event,release_scope,release_dependency,conflict,enterprise_rollup}_service.py` | Query construction + ordering + `fetch_page` | Modify |
| `app/services/booking_request_service.py` | New home for the `booking_requests` list query | Modify (add function) |
| `app/services/release_system_service.py` | New module — `releases/{id}/systems` has no service today | **Create** |
| `tests/test_pagination.py` | Primitive tests + the parametrised conformance sweep | Modify |
| `tests/test_pagination_ordering.py` | Paging-over-ties test (PostgreSQL-meaningful) | **Create** |
| `docs/pagination.md`, `CLAUDE.md` | Record what is bounded, what never will be, and the ordering rule | Modify |

---

## Task 1: Extend the primitive

Adds the factory and the row variant, and fixes the latent ordering bug in the three endpoints that are *already* bounded.

**Files:**
- Modify: `app/core/pagination.py`
- Modify: `app/api/v1/environments.py:47`, `app/api/v1/systems.py:28`, `app/api/v1/incidents.py:52`
- Modify: `app/services/environment_service.py:45`, `app/services/system_service.py:21`, `app/services/incident_service.py:117`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Produces: `pagination(*, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT) -> Callable[..., Page]`
- Produces: `fetch_page_rows(db: AsyncSession, query: Select, page: Optional[Page]) -> tuple[list[Row], int]`
- Unchanged: `fetch_page(db, query, page) -> tuple[list, int]`, `set_total_count(response, total)`, `Page`, `DEFAULT_LIMIT`, `MAX_LIMIT`, `TOTAL_COUNT_HEADER`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pagination.py`:

```python
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.pagination import fetch_page_rows, pagination


# ── the factory ──────────────────────────────────────────────────────────────
#
# Tested against a throwaway app rather than a real endpoint: no endpoint uses
# per-endpoint overrides until a later task, and the factory's whole contract is
# visible from one route.


def _probe_app(**overrides) -> FastAPI:
    probe = FastAPI()

    @probe.get("/probe")
    async def _probe(page: Page = Depends(pagination(**overrides))):
        return {"limit": page.limit, "offset": page.offset}

    return probe


@pytest.mark.asyncio
async def test_factory_defaults_to_the_shared_window():
    async with AsyncClient(
        transport=ASGITransport(app=_probe_app()), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"limit": DEFAULT_LIMIT, "offset": 0}
        assert (await ac.get(f"/probe?limit={MAX_LIMIT}")).status_code == 200
        assert (await ac.get(f"/probe?limit={MAX_LIMIT + 1}")).status_code == 422


@pytest.mark.asyncio
async def test_factory_overrides_are_enforced_not_clamped():
    """A per-endpoint cap is a real 422, so a caller cannot opt out of it."""
    app_50_200 = _probe_app(default_limit=50, max_limit=200)
    async with AsyncClient(
        transport=ASGITransport(app=app_50_200), base_url="http://probe"
    ) as ac:
        assert (await ac.get("/probe")).json() == {"limit": 50, "offset": 0}
        assert (await ac.get("/probe?limit=200")).status_code == 200
        assert (await ac.get("/probe?limit=201")).status_code == 422


# ── the row variant ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_page_rows_returns_tuples_not_scalars(db_session, tenant):
    await _make_environments(db_session, tenant.id, 4)
    query = select(Environment.id, Environment.name).order_by(Environment.name)

    rows, total = await fetch_page_rows(db_session, query, Page(limit=2, offset=0))

    assert total == 4
    assert len(rows) == 2
    # each row is a tuple of the selected columns, not an entity
    assert [r[1] for r in rows] == ["env-000", "env-001"]


@pytest.mark.asyncio
async def test_fetch_page_rows_total_ignores_the_window(db_session, tenant):
    await _make_environments(db_session, tenant.id, 9)
    query = select(Environment, Environment.name).order_by(Environment.name)

    rows, total = await fetch_page_rows(db_session, query, Page(limit=3, offset=6))

    assert total == 9
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_fetch_page_rows_without_a_page_returns_everything(db_session, tenant):
    await _make_environments(db_session, tenant.id, 5)
    rows, total = await fetch_page_rows(
        db_session, select(Environment.id, Environment.name), None
    )
    assert len(rows) == 5 == total
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_pagination.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_page_rows' from 'app.core.pagination'`

- [ ] **Step 3: Implement the factory and the row variant**

Replace the body of `app/core/pagination.py` below the `Page` dataclass with:

```python
def pagination(
    *, default_limit: int = DEFAULT_LIMIT, max_limit: int = MAX_LIMIT
) -> Callable[..., Page]:
    """Build the FastAPI dependency supplying the window for a list endpoint.

    Most endpoints want the shared default. The two that already had their own
    limit contract when this primitive arrived keep it by passing overrides,
    because both do per-row work after the query — raising their default would
    multiply real work, not just serialisation.
    """

    def _pagination(
        limit: int = Query(
            default_limit,
            ge=1,
            le=max_limit,
            description=f"Maximum rows to return (max {max_limit}).",
        ),
        offset: int = Query(0, ge=0, description="Rows to skip."),
    ) -> Page:
        return Page(limit=limit, offset=offset)

    return _pagination


def _window(query: Select, page: Optional[Page]) -> Select:
    if page is None:
        return query
    return query.limit(page.limit).offset(page.offset)


async def _total_for(db: AsyncSession, query: Select) -> int:
    """Count against the same filters, as a separate query rather than a window
    function, so it stays correct for joins and DISTINCT where a window count
    would double-count.
    """
    return (
        await db.execute(
            select(func.count()).select_from(query.order_by(None).subquery())
        )
    ).scalar_one()


async def fetch_page(
    db: AsyncSession, query: Select, page: Optional[Page]
) -> tuple[list, int]:
    """Run `query` windowed by `page`, and return (entities, total)."""
    total = await _total_for(db, query)
    rows = list((await db.execute(_window(query, page))).scalars().all())
    return rows, total


async def fetch_page_rows(
    db: AsyncSession, query: Select, page: Optional[Page]
) -> tuple[list, int]:
    """As `fetch_page`, but for multi-column selects.

    `fetch_page` ends in `.scalars()`, which keeps only the first column. A query
    like `select(Deployment, Build.git_sha, Environment.name)` needs whole rows.
    """
    total = await _total_for(db, query)
    rows = list((await db.execute(_window(query, page))).all())
    return rows, total
```

Add to the imports at the top of the file:

```python
from typing import Callable, Optional
```

- [ ] **Step 4: Migrate the three existing call sites to the factory**

In each of `app/api/v1/environments.py:47`, `app/api/v1/systems.py:28`, `app/api/v1/incidents.py:52`, change:

```python
    page: Page = Depends(pagination),
```
to:
```python
    page: Page = Depends(pagination()),
```

- [ ] **Step 5: Add tiebreakers to the three already-bounded services**

These three are bounded today with a non-unique sort, so they can already return duplicate and missing rows across pages. Fix them here rather than leaving a known bug in shipped code.

`app/services/environment_service.py:45`:
```python
    query = query.order_by(Environment.name, Environment.id)
```

`app/services/system_service.py:21`:
```python
        .order_by(System.name, System.id)
```

`app/services/incident_service.py:117`:
```python
    query = select(Incident).where(and_(*conds)).order_by(
        Incident.detected_at.desc(), Incident.id
    )
```

- [ ] **Step 6: Run the full suite on SQLite**

Run: `cd backend && uv run pytest -q`
Expected: PASS — all tests, including the pre-existing pagination tests.

- [ ] **Step 7: Run the full suite on PostgreSQL**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/core/pagination.py backend/app/api/v1/environments.py \
        backend/app/api/v1/systems.py backend/app/api/v1/incidents.py \
        backend/app/services/environment_service.py backend/app/services/system_service.py \
        backend/app/services/incident_service.py backend/tests/test_pagination.py
git commit -m "feat(api): add a pagination factory and a row-returning fetch_page

The factory lets an endpoint keep its own limit contract; the row variant
serves multi-column selects, which .scalars() cannot.

Also adds primary-key tiebreakers to the three endpoints bounded so far.
All three sorted on a non-unique column, so LIMIT/OFFSET over them could
already return a row on two pages and omit another."
```

---

## Task 2: Conformance sweep harness

Builds the parametrised test first, covering only the three endpoints already bounded. Every later task adds its endpoints to the table, so the test drives each conversion.

**Files:**
- Modify: `tests/test_pagination.py`

**Interfaces:**
- Produces: `BOUNDED_ENDPOINTS: list[tuple[str, str, int]]` — `(id, url, max_limit)`. Later tasks append entries.

- [ ] **Step 1: Write the conformance sweep**

Append to `tests/test_pagination.py`:

```python
# ── conformance sweep ────────────────────────────────────────────────────────
#
# Every bounded endpoint must satisfy the same four invariants. All of them hold
# on an empty tenant — request validation and the count query do not need rows —
# so this table needs no fixtures.
#
# NOTE: this proves *shape*, not that the window is correct. An endpoint whose
# service filters in Python after the query would pass all four and still return
# wrong results. That is controlled by reading each service before converting it,
# not by this test.

BOUNDED_ENDPOINTS: list[tuple[str, str, int, str]] = [
    # (test id, url, max_limit, auth fixture name)
    ("environments", "/api/v1/environments/", MAX_LIMIT, "auth_headers"),
    ("systems", "/api/v1/systems/", MAX_LIMIT, "auth_headers"),
    ("incidents", "/api/v1/incidents", MAX_LIMIT, "auth_headers"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,max_limit,auth_fixture",
    [(url, cap, fix) for _id, url, cap, fix in BOUNDED_ENDPOINTS],
    ids=[_id for _id, _url, _cap, _fix in BOUNDED_ENDPOINTS],
)
async def test_bounded_endpoint_conformance(
    request, client, url, max_limit, auth_fixture
):
    headers = request.getfixturevalue(auth_fixture)
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text

    # 1. still a bare array — no client change was required by this work
    body = response.json()
    assert isinstance(body, list)

    # 2. the unwindowed total is advertised
    assert TOTAL_COUNT_HEADER in response.headers
    assert int(response.headers[TOTAL_COUNT_HEADER]) >= 0

    # 3. asking past the cap is a 422, not a silent clamp
    over = await client.get(f"{url}?limit={max_limit + 1}", headers=headers)
    assert over.status_code == 422
```

Deliberately **three** invariants, not four. An obvious fourth —
`assert len(body) <= max_limit` — would be `0 <= 500` against an empty tenant and
could never fail, so it would be an assertion that asserts nothing. That the
window is actually applied is proven against `fetch_page` and `fetch_page_rows`
directly in the primitive tests, where the rows exist to make it meaningful.

The table carries an auth fixture name from the start because `admin/tenants`
(Task 4) needs master-admin credentials, and retrofitting the column later would
mean rewriting every row.

- [ ] **Step 2: Run it to verify it passes for the three already-bounded endpoints**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k conformance -v`
Expected: PASS — 3 parametrised cases (`environments`, `systems`, `incidents`).

- [ ] **Step 3: Verify the harness actually fails an unbounded endpoint**

Temporarily add `("bookings", "/api/v1/bookings/", MAX_LIMIT, "auth_headers")` to `BOUNDED_ENDPOINTS`.

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k "conformance and bookings"`
Expected: FAIL on the `TOTAL_COUNT_HEADER in response.headers` assertion — proving the harness detects an unconverted endpoint rather than passing vacuously.

Then **remove** that temporary entry again; Task 3 adds it for real.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_pagination.py
git commit -m "test: add a conformance sweep for bounded list endpoints

One parametrised test asserting the four invariants every bounded endpoint
shares. Later conversions add a table row, so the test drives each one."
```

---

## Task 3: Convert bookings, change-requests and infrastructure-components

Three drop-ins: scalar selects, every filter already in SQL.

**Files:**
- Modify: `app/api/v1/bookings.py:47-71`, `app/services/booking_service.py:270-297`
- Modify: `app/api/v1/change_requests.py:29`, `app/services/change_request_service.py:498-540`
- Modify: `app/api/v1/infrastructure_components.py:23-41`, `app/services/infrastructure_component_service.py:21-46`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `pagination()`, `fetch_page`, `set_total_count` from Task 1; `BOUNDED_ENDPOINTS` from Task 2.
- Produces: the three services now return `(rows, total)` instead of `list`.

- [ ] **Step 1: Add the three endpoints to the conformance table**

In `tests/test_pagination.py`, extend `BOUNDED_ENDPOINTS`:

```python
    ("bookings", "/api/v1/bookings/", MAX_LIMIT, "auth_headers"),
    ("change_requests", "/api/v1/change-requests", MAX_LIMIT, "auth_headers"),
    ("infrastructure_components", "/api/v1/infrastructure-components/", MAX_LIMIT, "auth_headers"),
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k conformance`
Expected: FAIL — 3 failures, each on `assert TOTAL_COUNT_HEADER in response.headers`.

- [ ] **Step 3: Convert `booking_service.list_bookings`**

In `app/services/booking_service.py`, add the import:

```python
from app.core.pagination import Page, fetch_page
```

Change the signature and tail of `list_bookings` (line 270):

```python
async def list_bookings(
    db: AsyncSession,
    tenant_id: int,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[str] = None,
    page: Optional[Page] = None,
) -> tuple[list[Booking], int]:
```

and replace the last three lines (`query = query.order_by(...)` through `return list(...)`) with:

```python
    query = query.order_by(Booking.start_date.asc(), Booking.id)
    return await fetch_page(db, query, page)
```

- [ ] **Step 4: Convert the bookings endpoint**

In `app/api/v1/bookings.py`, add to the imports:

```python
from app.core.pagination import Page, pagination, set_total_count
```

Replace the endpoint (line 47):

```python
@router.get("/", response_model=list[BookingResponse])
async def list_bookings(
    response: Response,
    environment_id: Optional[int] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    booking_status: Optional[str] = None,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    bookings, total = await booking_service.list_bookings(
        db,
        current_user.active_tenant_id,
        environment_id=environment_id,
        start=start,
        end=end,
        booking_status=booking_status,
        page=page,
    )
    set_total_count(response, total)
    responses: list[BookingResponse] = []
    for b in bookings:
        resp = _to_response(b)
        resp.has_unacknowledged_conflicts = await conflict_service.has_unacknowledged_conflicts(
            db, b.id, current_user.active_tenant_id
        )
        responses.append(resp)
    return responses
```

Ensure `Response` is imported from `fastapi` at the top of the file.

- [ ] **Step 5: Fix the other callers of `list_bookings`**

The service now returns a tuple. Find every caller:

Run: `cd backend && grep -rn "list_bookings(" app/ tests/ | grep -v "def list_bookings"`

For each call site outside the endpoint above, unpack the tuple — e.g. `rows, _ = await booking_service.list_bookings(...)`. Callers that passed no `page` keep their previous behaviour (all rows).

- [ ] **Step 6: Convert `change_request_service.list_change_requests`**

In `app/services/change_request_service.py`, add `from app.core.pagination import Page, fetch_page`, change the return annotation to `-> tuple[list[ChangeRequest], int]`, add `page: Optional[Page] = None` as the last keyword parameter, and replace the final two lines (line 539):

```python
    stmt = stmt.order_by(ChangeRequest.scheduled_start.desc(), ChangeRequest.id)
    return await fetch_page(db, stmt, page)
```

- [ ] **Step 7: Convert the change-requests endpoint**

In `app/api/v1/change_requests.py`, add the pagination imports and `Response`, then add `response: Response` as the first parameter and `page: Page = Depends(pagination())` to `list_change_requests` (line 29), pass `page=page` through to the service, unpack `rows, total`, and call `set_total_count(response, total)` before returning `rows`.

- [ ] **Step 8: Fix the other callers of `list_change_requests`**

Run: `cd backend && grep -rn "list_change_requests(" app/ tests/ | grep -v "def list_change_requests"`
Unpack the tuple at each call site.

- [ ] **Step 9: Convert `infrastructure_component_service.list_infrastructure_components`**

In `app/services/infrastructure_component_service.py`, add `from app.core.pagination import Page, fetch_page`, add `page: Optional[Page] = None`, change the return annotation to `-> tuple[list[InfrastructureComponent], int]`, and replace the last three lines (line 44):

```python
    query = query.order_by(InfrastructureComponent.name, InfrastructureComponent.id)
    return await fetch_page(db, query, page)
```

- [ ] **Step 10: Convert the infrastructure-components endpoint**

In `app/api/v1/infrastructure_components.py`, add the pagination imports and `Response`, add `response: Response` and `page: Page = Depends(pagination())` to `list_components` (line 23), pass `page=page`, unpack, set the header, return the rows.

- [ ] **Step 11: Fix the other callers**

Run: `cd backend && grep -rn "list_infrastructure_components(" app/ tests/ | grep -v "def list_"`
Unpack the tuple at each call site.

- [ ] **Step 12: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 13: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound bookings, change requests and infrastructure components"
```

---

## Task 4: Convert environments/health, admin/tenants and tenant/users

Three more drop-ins. `tenant/users` has no `ORDER BY` at all today.

**Files:**
- Modify: `app/api/v1/environment_health.py:41`, `app/services/environment_health_service.py:74-92`
- Modify: `app/api/v1/admin.py:23`, `app/services/tenant_service.py:12-14`
- Modify: `app/api/v1/tenant_admin.py:46`, `app/services/user_admin_service.py:10-14`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `pagination()`, `fetch_page`, `set_total_count`, `BOUNDED_ENDPOINTS`.
- Produces: `tenant_service.list_tenants(db, page=None) -> tuple[list[Tenant], int]`; `user_admin_service.list_users(db, tenant_id, page=None) -> tuple[list[User], int]`; `environment_health_service.health_overview(db, tenant_id, now=None, page=None) -> tuple[list[dict], int]`.

- [ ] **Step 1: Add the three endpoints to the conformance table**

```python
    ("environment_health", "/api/v1/environments/health", MAX_LIMIT, "auth_headers"),
    ("admin_tenants", "/api/v1/admin/tenants", MAX_LIMIT, "master_admin_headers"),
    ("tenant_users", "/api/v1/tenant/users", MAX_LIMIT, "auth_headers"),
```

`admin/tenants` requires master admin and `tenant/users` requires tenant admin. The `auth_headers` fixture is an `Admin` in `test_tenant`, which satisfies `require_tenant_admin` but **not** `require_master_admin`. So `admin_tenants` needs a master-admin header. Add this fixture to `tests/test_pagination.py`:

```python
@pytest_asyncio.fixture
async def master_admin_headers(client, db_session):
    """Bearer headers for a master admin in the system tenant."""
    from app.db.models.user import Tenant, User
    from app.core.security import get_password_hash

    system = Tenant(name="System", slug="system-pagination")
    db_session.add(system)
    await db_session.flush()
    user = User(
        tenant_id=system.id,
        username="pagination-masteradmin",
        email="ma@test.com",
        password_hash=get_password_hash("password123"),
        role="Admin",
        is_active=True,
        is_master_admin=True,
    )
    db_session.add(user)
    await db_session.commit()
    response = await client.post("/api/v1/auth/login", json={
        "username": user.username,
        "password": "password123",
        "tenant_slug": system.slug,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
```

Add `import pytest_asyncio` at the top of the file if not already present.

The sweep already reads its auth fixture per row (Task 2), so no change to the test body is needed.

- [ ] **Step 2: Run to verify the three new ones fail**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k conformance`
Expected: FAIL — 3 failures (`environment_health`, `admin_tenants`, `tenant_users`); the six from earlier tasks still pass.

- [ ] **Step 3: Convert `tenant_service.list_tenants`**

```python
async def list_tenants(
    db: AsyncSession, page: Optional[Page] = None
) -> tuple[list[Tenant], int]:
    query = select(Tenant).order_by(Tenant.name, Tenant.id)
    return await fetch_page(db, query, page)
```

Add `from typing import Optional` and `from app.core.pagination import Page, fetch_page`.

- [ ] **Step 4: Convert `user_admin_service.list_users`**

This one has no ordering today, so the tiebreaker is the whole ordering:

```python
async def list_users(
    db: AsyncSession, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[User], int]:
    query = (
        select(User)
        .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
        .order_by(User.username, User.id)
    )
    return await fetch_page(db, query, page)
```

- [ ] **Step 5: Convert `environment_health_service.health_overview`**

The environment query is windowed; the per-environment enrichment is unchanged, because it never drops a row.

```python
async def health_overview(
    db: AsyncSession,
    tenant_id: int,
    now: Optional[datetime] = None,
    page: Optional[Page] = None,
) -> tuple[list[dict], int]:
    now = now or datetime.now(timezone.utc)
    query = select(Environment).where(
        Environment.tenant_id == tenant_id,
        Environment.deleted_at.is_(None),
        Environment.status != "decommissioned",
    ).order_by(Environment.name.asc(), Environment.id)
    envs, total = await fetch_page(db, query, page)
    rows = []
    for env in envs:
        current, last_at = _derive_status(await _latest(db, tenant_id, env.id), now)
        booking = await _active_booking(db, tenant_id, env.id, now)
        outage = await _planned_outage(db, tenant_id, env.id, now)
        alert = current in ("down", "issue") and booking is not None and not outage
        rows.append({
            "environment_id": env.id, "environment_name": env.name,
            "current_status": current, "last_recorded_at": last_at,
            "active_booking": booking is not None, "active_booking_summary": booking,
            "planned_outage": outage, "alert": alert,
        })
    return rows, total
```

- [ ] **Step 6: Convert the three endpoints**

Each gets `response: Response`, `page: Page = Depends(pagination())`, an unpacked `(rows, total)`, and `set_total_count(response, total)`.

`app/api/v1/admin.py:23`:
```python
@router.get("/tenants", response_model=list[TenantResponse])
async def list_tenants(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_master_admin()),
):
    rows, total = await tenant_service.list_tenants(db, page=page)
    set_total_count(response, total)
    return rows
```

`app/api/v1/tenant_admin.py:46`:
```python
@router.get("/users", response_model=list[UserResponse])
async def list_users(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    rows, total = await user_admin_service.list_users(
        db, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return rows
```

`app/api/v1/environment_health.py:41`:
```python
@router.get("/health", response_model=list[EnvironmentHealthOverviewRow])
async def health_overview(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return the health overview for all non-decommissioned environments in the tenant (JWT auth)."""
    rows, total = await svc.health_overview(db, current_user.active_tenant_id, page=page)
    set_total_count(response, total)
    return rows
```

Add the pagination and `Response` imports to each file.

- [ ] **Step 7: Fix the other callers**

Run: `cd backend && grep -rn "list_tenants(\|list_users(\|health_overview(" app/ tests/ scripts/ | grep -v "def "`
Unpack the tuple at each call site. Pay particular attention to `scripts/` — the tenant backfill scripts call services directly.

- [ ] **Step 8: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound environment health, admin tenants and tenant users

tenant/users had no ORDER BY at all, so its pages were previously undefined
even before a window was applied."
```

---

## Task 5: Convert the release sub-resource lists

Four drop-ins scoped to one release: events, changes, scope, dependencies. `phases` and `gates` are deliberately excluded — they are capped by the release template.

**Files:**
- Modify: `app/api/v1/releases.py` — `list_events` (983), `list_changes` (1008), `list_dependencies` (924), and the scope list
- Modify: `app/services/release_event_service.py:148-161`, `app/services/release_scope_service.py:208-226`, `app/services/release_dependency_service.py:57-70`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `pagination()`, `fetch_page`, `set_total_count`, `BOUNDED_ENDPOINTS`.
- Produces: the three services return `(rows, total)`.
- Note: these URLs need a real release id, so the conformance entries are built per-test rather than as static strings — see Step 1.

- [ ] **Step 1: Add a release-scoped conformance sweep**

These endpoints 404 without a real release, so they cannot use the static table. Add a second parametrised test to `tests/test_pagination.py`:

```python
RELEASE_SUBRESOURCES: list[tuple[str, str]] = [
    # (test id, path suffix)
    ("events", "events"),
    ("changes", "changes"),
    ("dependencies", "dependencies"),
]


@pytest_asyncio.fixture
async def release_id(db_session, test_tenant, test_user) -> int:
    """A persisted release in test_tenant."""
    from app.db.models.release import Release

    release = Release(
        tenant_id=test_tenant.id,
        name="pagination-release",
        release_type="standard",
        status="planned",
        raised_by=test_user.id,
    )
    db_session.add(release)
    await db_session.commit()
    await db_session.refresh(release)
    return release.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "suffix",
    [suffix for _id, suffix in RELEASE_SUBRESOURCES],
    ids=[_id for _id, _suffix in RELEASE_SUBRESOURCES],
)
async def test_release_subresource_conformance(
    client, auth_headers, release_id, suffix
):
    url = f"/api/v1/releases/{release_id}/{suffix}"
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text

    body = response.json()
    assert isinstance(body, list)
    assert TOTAL_COUNT_HEADER in response.headers

    over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
    assert over.status_code == 422
```

Check the `Release` model's required columns before running — if `raised_by` or `release_type` differ from the above, match the model. Run `grep -n "class Release" -A 30 app/db/models/release.py` to confirm.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k subresource`
Expected: FAIL — 3 failures on the missing `X-Total-Count` header.

- [ ] **Step 3: Convert `release_event_service.list_events`**

```python
async def list_events(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseEvent], int]:
    query = select(ReleaseEvent).where(
        ReleaseEvent.release_id == release_id,
        ReleaseEvent.tenant_id == tenant_id,
    ).order_by(ReleaseEvent.occurred_at.desc(), ReleaseEvent.id)
    return await fetch_page(db, query, page)
```

- [ ] **Step 4: Convert `release_scope_service.list_changes`**

Its ordering is already total (`ReleaseChange.id`), so only the return shape changes:

```python
async def list_changes(
    db: AsyncSession,
    release_id: Optional[int],
    tenant_id: int,
    backlog: bool = False,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseChange], int]:
    """List scope items. Pass `release_id` for a specific release; pass
    `backlog=True` for unassigned items (release_id IS NULL)."""
    stmt = select(ReleaseChange).where(
        ReleaseChange.tenant_id == tenant_id,
        ReleaseChange.deleted_at.is_(None),
    )
    if backlog:
        stmt = stmt.where(ReleaseChange.release_id.is_(None))
    elif release_id is not None:
        stmt = stmt.where(ReleaseChange.release_id == release_id)
    stmt = stmt.order_by(ReleaseChange.id)
    return await fetch_page(db, stmt, page)
```

- [ ] **Step 5: Convert `release_dependency_service.list_dependencies`**

```python
async def list_dependencies(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseDependency], int]:
    query = select(ReleaseDependency).where(
        ReleaseDependency.release_id == release_id,
        ReleaseDependency.tenant_id == tenant_id,
    ).order_by(ReleaseDependency.id)
    return await fetch_page(db, query, page)
```

- [ ] **Step 6: Convert the endpoints**

`list_events` in `app/api/v1/releases.py:983`:
```python
@router.get("/{release_id}/events", response_model=list[ReleaseEventRead])
async def list_events(
    release_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows, total = await release_event_service.list_events(
        db, release_id, tenant_id, page=page
    )
    set_total_count(response, total)
    return rows
```

`list_changes` at line 1008 — note the enrichment loop stays exactly as it is, because it decorates rather than filters:
```python
@router.get("/{release_id}/changes", response_model=list[ReleaseChangeRead])
async def list_changes(
    release_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    release = await _require_release(db, release_id, tenant_id)
    rows, total = await release_scope_service.list_changes(
        db, release_id, tenant_id, page=page
    )
    set_total_count(response, total)
    creep_ids = await release_scope_service.scope_creep_change_ids(db, release, tenant_id)
    out: list[ReleaseChangeRead] = []
    for r in rows:
        item = ReleaseChangeRead.model_validate(r)
        item.is_scope_creep = r.id in creep_ids
        out.append(item)
    return out
```

`list_dependencies` at line 924 — same shape: add `response`, `page`, unpack, set the header.

Also convert the scope list endpoint that calls `list_changes` with `backlog=True`, following the same pattern.

Add `from app.core.pagination import Page, pagination, set_total_count` to `app/api/v1/releases.py` and confirm `Response` is imported from `fastapi`.

- [ ] **Step 7: Fix the other callers**

Run: `cd backend && grep -rn "list_events(\|list_changes(\|list_dependencies(" app/ tests/ | grep -v "def "`
Unpack the tuple at each call site. `enterprise_report_service` and `release_scope_service` internals are likely callers — check each.

- [ ] **Step 8: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound release events, changes, scope and dependencies

Phases and gates stay unbounded: both are capped by the release template,
so a limit would be a knob with no benefit."
```

---

## Task 6: Set the total on `GET /releases`

`release_service.list_releases` has always returned `(rows, total)`; the endpoint discarded the total. This swaps its hand-rolled `limit`/`offset` for the factory with its existing contract preserved.

**Files:**
- Modify: `app/api/v1/releases.py:137-165`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `pagination(default_limit=50, max_limit=200)` from Task 1.
- `release_service.list_releases` is **unchanged** — it already takes `limit`/`offset` and returns `(rows, total)`.

- [ ] **Step 1: Add the endpoint to the conformance table**

```python
    ("releases", "/api/v1/releases", 200, "auth_headers"),
```

Note the max is **200**, not `MAX_LIMIT` — this endpoint keeps its own contract.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k "conformance and releases"`
Expected: FAIL on the missing `X-Total-Count` header.

- [ ] **Step 3: Convert the endpoint**

In `app/api/v1/releases.py:137`, replace the `limit` and `offset` parameters with the factory dependency and set the header:

```python
@router.get("", response_model=list[ReleaseListItemRead])
async def list_releases(
    response: Response,
    release_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    owner_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    release_kind: Optional[str] = Query(None, pattern="^(project|enterprise)$"),
    system_id: Optional[int] = Query(None),
    page: Page = Depends(pagination(default_limit=50, max_limit=200)),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    releases, total = await release_service.list_releases(
        db,
        tenant_id,
        release_type=release_type,
        status=status_filter,
        date_from=date_from,
        date_to=date_to,
        owner_id=owner_id,
        search=search,
        release_kind=release_kind,
        system_id=system_id,
        limit=page.limit,
        offset=page.offset,
    )
    set_total_count(response, total)
    if not releases:
        return []
    release_ids = [r.id for r in releases]
```

The rest of the function body is unchanged.

- [ ] **Step 4: Add the tiebreaker to `release_service.list_releases`**

Find its `order_by` (around line 288 in `app/services/release_service.py`) and append `Release.id` as the final sort key, preserving whatever the primary sort currently is.

Run: `cd backend && grep -n "order_by" app/services/release_service.py` to locate it.

- [ ] **Step 5: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): advertise the total on GET /releases

The service always returned it; the endpoint dropped it on the floor. The
50/200 contract is preserved via the pagination factory."
```

---

## Task 7: Convert `GET /deployments` to the row variant

Already windowed by hand, but selects a five-column join, so it needs `fetch_page_rows`.

**Files:**
- Modify: `app/api/v1/deployments.py:39-85`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `fetch_page_rows`, `pagination(default_limit=100, max_limit=500)`, `set_total_count`.

- [ ] **Step 1: Add to the conformance table and write a shape test**

```python
    ("deployments", "/api/v1/deployments", 500, "auth_headers"),
```

Plus a targeted test that the row variant preserves the five-tuple the response builder expects:

```python
@pytest.mark.asyncio
async def test_deployments_rows_keep_their_join_columns(
    client, auth_headers, db_session, test_tenant, test_environment
):
    """The row variant must hand back (Deployment, sha, env, release, cr), not scalars."""
    from app.db.models.deployment import Deployment

    db_session.add(Deployment(
        tenant_id=test_tenant.id,
        environment_id=test_environment.id,
        status="succeeded",
        deployed_at=datetime.now(timezone.utc),
    ))
    await db_session.commit()

    response = await client.get("/api/v1/deployments", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    # environment_name comes from the join, not the Deployment row
    assert body[0]["environment_name"] == test_environment.name
```

Add `from datetime import datetime, timezone` to the test file imports if absent. Confirm the `Deployment` model's required columns first with `grep -n "class Deployment" -A 30 app/db/models/deployment.py`, and match them.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k "deployments"`
Expected: FAIL — conformance fails on the missing header.

- [ ] **Step 3: Convert the endpoint**

In `app/api/v1/deployments.py`, add:

```python
from app.core.pagination import Page, pagination, set_total_count, fetch_page_rows
```

Replace `list_deployments` (line 49):

```python
@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    response: Response,
    environment_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    build_id: Optional[int] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    page: Page = Depends(pagination(default_limit=100, max_limit=500)),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = _select_with_joins().where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.deleted_at.is_(None),
    )
    if environment_id is not None:
        q = q.where(Deployment.environment_id == environment_id)
    if release_id is not None:
        q = q.where(Deployment.release_id == release_id)
    if build_id is not None:
        q = q.where(Deployment.build_id == build_id)
    if status_filter is not None:
        q = q.where(Deployment.status == status_filter)
    if date_from is not None:
        q = q.where(Deployment.deployed_at >= date_from)
    if date_to is not None:
        q = q.where(Deployment.deployed_at <= date_to)
    q = q.order_by(Deployment.deployed_at.desc(), Deployment.id)
    rows, total = await fetch_page_rows(db, q, page)
    set_total_count(response, total)
    return [
        _deployment_to_read(d, sha, env_name, rel_name, cr_title)
        for d, sha, env_name, rel_name, cr_title in rows
    ]
```

Ensure `Response` is imported from `fastapi`.

- [ ] **Step 4: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound deployments via the row-returning fetch_page

Keeps its existing 100/500 contract and now advertises the total."
```

---

## Task 8: Convert conflicts and rollup/scope to the row variant

Two more multi-column selects, both with every filter already in SQL.

**Files:**
- Modify: `app/api/v1/conflicts.py:20-46`, `app/services/conflict_service.py:27-65`
- Modify: `app/api/v1/enterprise_rollup.py:36-53`, `app/services/enterprise_rollup_service.py:68-123`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Consumes: `fetch_page_rows`, `pagination()`, `set_total_count`.
- Produces: `conflict_service.list_conflicts(db, booking_id, tenant_id, page=None) -> tuple[list[ConflictingBooking], int]`; `enterprise_rollup_service.scope_rollup(..., page=None) -> tuple[list[ScopeRollupItem], int]`.

- [ ] **Step 1: Write the failing tests**

These are both nested under a parent id, so they get their own targeted tests rather than table entries:

```python
@pytest.mark.asyncio
async def test_conflicts_advertises_its_total(client, auth_headers, test_booking):
    booking_id = test_booking.bookings[0].id
    response = await client.get(
        f"/api/v1/bookings/{booking_id}/conflicts", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    assert TOTAL_COUNT_HEADER in response.headers

    over = await client.get(
        f"/api/v1/bookings/{booking_id}/conflicts?limit={MAX_LIMIT + 1}",
        headers=auth_headers,
    )
    assert over.status_code == 422
```

Check the `test_booking` fixture's return shape first (`grep -n "async def test_booking" -A 30 tests/conftest.py`) and adjust `test_booking.bookings[0].id` to match what it actually yields.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k conflicts`
Expected: FAIL on the missing header.

- [ ] **Step 3: Convert `conflict_service.list_conflicts`**

The early return for a terminal-state booking must return the tuple shape too:

```python
async def list_conflicts(
    db: AsyncSession, booking_id: int, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[ConflictingBooking], int]:
    """Return other bookings conflicting with booking_id — same env, overlapping window,
    neither in a lifecycle-defined terminal state. The result is enriched with the
    parent-request project name and environment name so UIs can show a human-readable
    label instead of "Booking #N".
    """
    me = (await db.execute(
        select(Booking).where(Booking.id == booking_id, Booking.tenant_id == tenant_id)
    )).scalar_one_or_none()
    if me is None or me.status in TERMINAL_STATES:
        return [], 0

    stmt = (
        select(Booking, BookingRequest.project_name, Environment.name)
        .join(BookingRequest, BookingRequest.id == Booking.booking_request_id, isouter=True)
        .join(Environment, Environment.id == Booking.environment_id, isouter=True)
        .where(
            Booking.tenant_id == tenant_id,
            Booking.id != me.id,
            Booking.environment_id == me.environment_id,
            Booking.deleted_at.is_(None),
            not_(Booking.status.in_(TERMINAL_STATES)),
            # half-open overlap: [start, end)
            Booking.start_date < me.end_date,
            Booking.end_date > me.start_date,
        )
        .order_by(Booking.start_date, Booking.id)
    )
    rows, total = await fetch_page_rows(db, stmt, page)
    return [
        ConflictingBooking(
            booking=b,
            project_name=project_name,
            environment_name=env_name,
        )
        for b, project_name, env_name in rows
    ], total
```

Add `from app.core.pagination import Page, fetch_page_rows` and `from typing import Optional`.

- [ ] **Step 4: Convert the conflicts endpoint**

`app/api/v1/conflicts.py:20` — add `response: Response` and `page: Page = Depends(pagination())`, unpack `others, total`, and call `set_total_count(response, total)` before the enrichment loop. The loop body is unchanged.

- [ ] **Step 5: Convert `enterprise_rollup_service.scope_rollup`**

Both early returns become `return [], 0`. The tail becomes:

```python
    stmt = stmt.order_by(ReleaseChange.id)
    rows, total = await fetch_page_rows(db, stmt, page)

    items: list[ScopeRollupItem] = []
    for rc, rel, sys in rows:
        items.append(ScopeRollupItem(
            release_change_id=rc.id,
            project_release_id=rel.id,
            project_release_name=rel.name,
            external_key=rc.external_key,
            title=rc.title,
            change_kind=rc.change_kind,
            external_status=rc.external_status,
            system_id=rc.system_id,
            system_name=sys.name if sys else None,
        ))
    return items, total
```

Add `page: Optional[Page] = None` as the final keyword parameter and change the return annotation to `-> tuple[list[ScopeRollupItem], int]`.

Note the query had **no** `order_by` at all before, so `ReleaseChange.id` is the whole ordering.

- [ ] **Step 6: Convert the rollup/scope endpoint**

`app/api/v1/enterprise_rollup.py:36` — add `response: Response` and `page: Page = Depends(pagination())`, pass `page=page`, unpack, set the header.

Leave `rollup/systems`, `rollup/members`, `rollup/timeline`, `rollup/raid` and `report` **untouched** — they are aggregations, permanently unbounded by decision.

- [ ] **Step 7: Fix the other callers**

Run: `cd backend && grep -rn "list_conflicts(\|scope_rollup(" app/ tests/ | grep -v "def "`
Unpack the tuple at each call site — `enterprise_report_service` calls `scope_rollup`.

- [ ] **Step 8: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound booking conflicts and the enterprise scope rollup

The other rollup endpoints stay unbounded by decision: they are aggregate
views, and a partial rollup is a wrong rollup."
```

---

## Task 9: Extract the `booking_requests` list into its service

Moves an inline query out of the endpoint and replaces a per-row `db.refresh` with an eager load.

**Files:**
- Modify: `app/api/v1/booking_requests.py:110-125`
- Modify: `app/services/booking_request_service.py`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Produces: `booking_request_service.list_booking_requests(db, tenant_id, page=None) -> tuple[list[BookingRequest], int]`, with `BookingRequest.bookings` eagerly loaded on every row.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.asyncio
async def test_booking_requests_still_include_their_bookings(
    client, auth_headers, test_booking
):
    """The eager load must replace the per-row refresh without losing the relation."""
    response = await client.get("/api/v1/booking-requests", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) >= 1
    assert "bookings" in body[0]
    assert len(body[0]["bookings"]) >= 1
```

Add the table entry too:
```python
    ("booking_requests", "/api/v1/booking-requests", MAX_LIMIT, "auth_headers"),
```

- [ ] **Step 2: Run to verify the conformance case fails**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k booking_requests`
Expected: FAIL on the missing header (the relation test may already pass — that is fine, it is a regression guard for the refactor).

- [ ] **Step 3: Add the service function**

In `app/services/booking_request_service.py`:

```python
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.pagination import Page, fetch_page
from app.db.models.booking_request import BookingRequest


async def list_booking_requests(
    db: AsyncSession, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[BookingRequest], int]:
    """Tenant's booking requests, newest first, with child bookings eagerly loaded.

    The eager load replaces a per-row `db.refresh`, which was one round trip per
    request row.
    """
    query = (
        select(BookingRequest)
        .options(selectinload(BookingRequest.bookings))
        .where(
            BookingRequest.tenant_id == tenant_id,
            BookingRequest.deleted_at.is_(None),
        )
        .order_by(BookingRequest.created_at.desc(), BookingRequest.id)
    )
    return await fetch_page(db, query, page)
```

Check which imports the module already has and avoid duplicating them.

- [ ] **Step 4: Replace the endpoint body**

`app/api/v1/booking_requests.py:110`:

```python
@router.get("", response_model=list[BookingRequestResponse])
async def list_booking_requests(
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    rows, total = await booking_request_service.list_booking_requests(
        db, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [_to_response(r) for r in rows]
```

Delete the now-unused function-local imports of `select` and `BookingRequest`. Add `from app.core.pagination import Page, pagination, set_total_count` and confirm `Response` is imported from `fastapi`.

- [ ] **Step 5: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "refactor(api): move the booking-requests list into its service

The query lived in the endpoint and was followed by a db.refresh per row.
selectinload replaces that N+1; bounding the page alone would only have
capped it at 500 round trips."
```

---

## Task 10: Extract `releases/{id}/systems` into a new service

There is no `release_system_service` today, and the query is a tuple select, so this needs both a new module and the row variant.

**Files:**
- Create: `app/services/release_system_service.py`
- Modify: `app/api/v1/releases.py:739-766`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Produces: `release_system_service.list_release_systems(db, release_id, tenant_id, page=None) -> tuple[list[Row], int]`, where each row is `(ReleaseSystem, system_name: str)`.

- [ ] **Step 1: Write the failing test**

Add `("systems", "systems")` to `RELEASE_SUBRESOURCES` from Task 5, plus a targeted test that the enrichment survives:

```python
@pytest.mark.asyncio
async def test_release_systems_keep_the_joined_system_name(
    client, auth_headers, db_session, test_tenant, release_id
):
    from app.db.models.release_system import ReleaseSystem
    from app.db.models.system import System

    system = System(tenant_id=test_tenant.id, name="payments")
    db_session.add(system)
    await db_session.flush()
    db_session.add(ReleaseSystem(
        tenant_id=test_tenant.id, release_id=release_id, system_id=system.id
    ))
    await db_session.commit()

    response = await client.get(
        f"/api/v1/releases/{release_id}/systems", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["system_name"] == "payments"
```

Confirm the `System` and `ReleaseSystem` models' required columns before running.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k "systems"`
Expected: FAIL on the missing `X-Total-Count` header.

- [ ] **Step 3: Create the service module**

`app/services/release_system_service.py`:

```python
"""Systems attached to a release.

Extracted from the endpoint when the list was bounded: the query is a
multi-column select (the joined system name is not a ReleaseSystem column), so
it goes through fetch_page_rows rather than fetch_page.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page, fetch_page_rows
from app.db.models.release_system import ReleaseSystem
from app.db.models.system import System


async def list_release_systems(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
) -> tuple[list, int]:
    """Return (ReleaseSystem, system_name) rows for a release, plus the total."""
    query = (
        select(ReleaseSystem, System.name)
        .join(System, System.id == ReleaseSystem.system_id)
        .where(
            ReleaseSystem.release_id == release_id,
            ReleaseSystem.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
        .order_by(ReleaseSystem.id)
    )
    return await fetch_page_rows(db, query, page)
```

- [ ] **Step 4: Replace the endpoint body**

`app/api/v1/releases.py:739`:

```python
@router.get("/{release_id}/systems", response_model=list[ReleaseSystemRead])
async def list_release_systems(
    release_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows, total = await release_system_service.list_release_systems(
        db, release_id, tenant_id, page=page
    )
    set_total_count(response, total)
    out: list[ReleaseSystemRead] = []
    for rs, name in rows:
        item = ReleaseSystemRead.model_validate(rs)
        item.system_name = name
        out.append(item)
    return out
```

Delete the function-local model imports and add `release_system_service` to the module's service imports.

- [ ] **Step 5: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "refactor(api): extract release systems into a service and bound it"
```

---

## Task 11: Extract `releases/{id}/history` into the service

> **Correction to the spec.** The spec proposed adding a `tenant_id` predicate to
> this query as defence in depth. That is not possible: `ReleaseStatusHistory`
> (`app/db/models/release.py:40`) has **no `tenant_id` column** — its columns are
> `release_id`, `from_state`, `to_state`, `changed_by`, `changed_at`, `notes`.
> The table is scoped transitively through its release, so `_require_release` is
> not merely the first line of defence, it is the only one available and it is
> correct. This task is therefore a plain extraction. The spec has been amended.

**Files:**
- Modify: `app/api/v1/releases.py:562-580`
- Modify: `app/services/release_service.py`
- Test: `tests/test_pagination.py`

**Interfaces:**
- Produces: `release_service.list_release_history(db, release_id, page=None) -> tuple[list[ReleaseStatusHistory], int]`

- [ ] **Step 1: Write the failing test**

Add `("history", "history")` to `RELEASE_SUBRESOURCES`, plus a guard that the extraction preserves the rows and their order:

```python
@pytest.mark.asyncio
async def test_release_history_survives_the_extraction(
    client, auth_headers, db_session, test_user, release_id
):
    from app.db.models.release import ReleaseStatusHistory

    now = datetime.now(timezone.utc)
    for n, (frm, to) in enumerate([("planned", "in_progress"), ("in_progress", "done")]):
        db_session.add(ReleaseStatusHistory(
            release_id=release_id,
            from_state=frm,
            to_state=to,
            changed_by=test_user.id,
            changed_at=now + timedelta(minutes=n),
        ))
    await db_session.commit()

    response = await client.get(
        f"/api/v1/releases/{release_id}/history", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["to_state"] for row in body] == ["in_progress", "done"]  # oldest first
```

Add `from datetime import datetime, timedelta, timezone` to the test file imports if absent.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination.py -q -k history`
Expected: FAIL on the missing header.

- [ ] **Step 3: Add the service function**

In `app/services/release_service.py`:

```python
async def list_release_history(
    db: AsyncSession,
    release_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseStatusHistory], int]:
    """Lifecycle state-change history for a release, oldest first.

    No tenant predicate: release_status_history has no tenant_id column — it is
    scoped through its release, and callers must check that with
    _require_release before calling here.
    """
    query = (
        select(ReleaseStatusHistory)
        .where(ReleaseStatusHistory.release_id == release_id)
        .order_by(ReleaseStatusHistory.changed_at.asc(), ReleaseStatusHistory.id)
    )
    return await fetch_page(db, query, page)
```

Import `ReleaseStatusHistory` at module level and add `Page`/`fetch_page` to the imports if absent.

- [ ] **Step 4: Replace the endpoint body**

```python
@router.get("/{release_id}/history", response_model=list[ReleaseStatusHistoryRead])
async def get_release_history(
    release_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return lifecycle state-change history for a release."""
    tenant_id = current_user.active_tenant_id
    await _require_release(db, release_id, tenant_id)
    rows, total = await release_service.list_release_history(db, release_id, page=page)
    set_total_count(response, total)
    return rows
```

- [ ] **Step 5: Run both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app backend/tests
git commit -m "refactor(api): extract release history into a service and bound it

No tenant predicate is added: release_status_history has no tenant_id column,
so _require_release is the correct and only isolation point."
```

---

## Task 12: Prove paging over ties is stable

The test that fails if any tiebreaker is dropped. Only meaningful on PostgreSQL.

**Files:**
- Create: `tests/test_pagination_ordering.py`

**Interfaces:**
- Consumes: `fetch_page` from Task 1, the tiebreakers added throughout.

- [ ] **Step 1: Write the test**

```python
"""Paging over ties.

LIMIT/OFFSET is only correct over a total order. If the ORDER BY leaves ties,
the database may break them differently between two queries, so a row can come
back on page 1 and page 2 while another never appears at all. Nothing errors.

SQLite's plans are stable enough that it usually passes this by luck, so the
PostgreSQL leg is the one that matters:

    TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
        uv run pytest tests/test_pagination_ordering.py -q
"""
import pytest

from app.core.pagination import Page, fetch_page
from app.services import environment_service


@pytest.mark.asyncio
async def test_walking_pages_over_identical_sort_keys_sees_each_row_once(
    db_session, test_tenant
):
    """Every environment shares a name, so `ORDER BY name` alone leaves 30 ties."""
    from app.db.models.environment import Environment

    total_rows = 30
    for _ in range(total_rows):
        db_session.add(Environment(
            tenant_id=test_tenant.id,
            name="identical",            # every row ties on the sort column
            environment_type="SIT",
        ))
    await db_session.flush()

    seen: list[int] = []
    page_size = 7
    offset = 0
    while True:
        rows, total = await environment_service.list_environments(
            db_session, test_tenant.id, page=Page(limit=page_size, offset=offset)
        )
        assert total == total_rows
        if not rows:
            break
        seen.extend(r.id for r in rows)
        offset += page_size

    assert len(seen) == total_rows, f"expected {total_rows} rows, saw {len(seen)}"
    assert len(set(seen)) == total_rows, "a row was returned on more than one page"
```

- [ ] **Step 2: Run it on SQLite**

Run: `cd backend && uv run pytest tests/test_pagination_ordering.py -q`
Expected: PASS

- [ ] **Step 3: Run it on PostgreSQL — the leg that matters**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_pagination_ordering.py -q`
Expected: PASS

- [ ] **Step 4: Prove the property directly rather than hoping the planner shuffles**

Relying on PostgreSQL to *choose* an unstable plan is not a test — the engine is permitted to be consistent, not required to be. Assert the property directly instead.

Add to `tests/test_pagination_ordering.py`:

```python
@pytest.mark.asyncio
async def test_only_the_total_order_gives_a_reproducible_sequence(
    db_session, test_tenant
):
    """The walk test above is only meaningful if the tiebreaker is what pins the
    sequence. Under `ORDER BY name` alone every row ties, so nothing in the SQL
    determines the order; adding the primary key makes it unique and sorted.
    """
    from app.db.models.environment import Environment

    for _ in range(20):
        db_session.add(Environment(
            tenant_id=test_tenant.id, name="identical", environment_type="SIT",
        ))
    await db_session.flush()

    total_order = select(Environment).order_by(Environment.name, Environment.id)

    first, _ = await fetch_page(db_session, total_order, Page(limit=20, offset=0))
    again, _ = await fetch_page(db_session, total_order, Page(limit=20, offset=0))

    ids = [r.id for r in first]
    assert ids == [r.id for r in again], "a total order must be reproducible"
    assert ids == sorted(ids), "the tiebreaker must determine the sequence"
    assert len(set(ids)) == 20
```

Add `from sqlalchemy import select` to the test file imports.

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_pagination_ordering.py -q`
Expected: PASS — both tests.

Do not leave a tiebreaker removed anywhere in the tree.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_pagination_ordering.py
git commit -m "test: walk pages over identical sort keys and assert each row appears once"
```

---

## Task 13: Update the documentation

**Files:**
- Modify: `docs/pagination.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Rewrite the "Bounded so far" and "Not yet bounded" sections of `docs/pagination.md`**

Move every endpoint bounded by Tasks 3–11 into the bounded table. Then replace the "Not yet bounded" section with three honest groups:

```markdown
## Not yet bounded

**Blocked on a query restructure.** Each of these filters or merges *after* the
query, so a SQL `LIMIT` would window the wrong set. Adding `limit` before the
restructure would be worse than leaving them unbounded — the results would be
quietly wrong rather than merely large.

- `GET /releases/{release_id}/raid` — `raid_service.list_items` applies its `rag`
  and `overdue` filters in Python, computed from probability/impact against
  tenant config and from review dates.
- `GET /systems/{system_id}/dependencies` and
  `GET /subsystems/{subsystem_id}/dependencies` — both execute two queries
  (outgoing and incoming) and concatenate the results. A `LIMIT` cannot window a
  concatenation of two separately-executed queries; they need a single
  `UNION ALL` first.

**Permanently unbounded — aggregations.** These are computed aggregate views,
not row lists, and three of them do not return arrays at all. A partial rollup
is a wrong rollup, so paginating them is not meaningful:
`rollup/systems`, `rollup/members`, `rollup/timeline`, `rollup/raid`, `report`.

`rollup/scope` is the exception and *is* bounded: it is a genuine row list with
every filter in SQL.

**Bounded in practice by tenant configuration**, where a cap would add a knob for
no benefit: `component_types`, `release_event_types`, `release_templates`,
`tenant_admin_fields`, `booking_lifecycle`, `api_keys`, and the per-release
`phases` and `gates` (both capped by the release template).
```

- [ ] **Step 2: Correct the `GET /releases` claim**

`docs/pagination.md` currently lists `releases` among the unbounded endpoints. It has always had its own 50/200 window; what it lacked was the header. Add to the primitive section:

```markdown
Two endpoints predate the shared primitive and keep their own limits, because
both do per-row work after the query: `GET /releases` (50/200) and
`GET /deployments` (100/500). They pass overrides to `pagination()` rather than
adopting the shared 500/1000.
```

- [ ] **Step 3: Add the total-ordering rule**

```markdown
## Ordering must be total

`LIMIT`/`OFFSET` is only correct over a total order. If the `ORDER BY` leaves
ties, the database may break them differently between two queries — a row comes
back on page 1 and page 2, another never appears, and nothing errors. Under
SQLite this usually looks fine; it shows up on PostgreSQL under concurrent
writes and larger result sets.

So every bounded endpoint ends its ordering with a unique tiebreaker, in
practice the primary key:

    query.order_by(Booking.start_date.asc(), Booking.id)

`tests/test_pagination_ordering.py` walks a result set whose rows all share a
sort key and asserts each row appears exactly once.
```

- [ ] **Step 4: Update the CLAUDE.md pitfall entry**

Replace the "Unbounded list endpoints" bullet with:

```markdown
- **Unbounded list endpoints** — new list endpoints take `page: Page = Depends(pagination())` and their service returns `(rows, total)` via `fetch_page` (or `fetch_page_rows` for multi-column selects); see [docs/pagination.md](docs/pagination.md). Order by a **unique** key — append the primary key as a tiebreaker, or pages will duplicate and drop rows. Never add `limit` to an endpoint whose service filters in Python after the query, or merges two executed queries — the page would be windowed before the filter and the results quietly wrong
```

- [ ] **Step 5: Update the CLAUDE.md status header**

The "Next" line lists 44 unbounded list endpoints. Update the count to what remains after this sweep, and note that RAID and the two `dependencies` endpoints are blocked on a restructure rather than merely pending.

- [ ] **Step 6: Commit**

```bash
git add docs/pagination.md CLAUDE.md
git commit -m "docs: record what the pagination sweep bounded, and what never will be"
```

---

## Task 14: Full verification and PR

- [ ] **Step 1: Run the whole suite on both engines**

Run: `cd backend && uv run pytest -q`
Expected: PASS, with the failure count and total printed.

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`
Expected: PASS

Record both totals — do not claim completion without them.

- [ ] **Step 2: Confirm no list endpoint was missed**

Run: `cd backend && grep -rn "response_model=list\[" app/api/v1/*.py | wc -l`
then cross-check each `GET` returning a list against the bounded table and the two "not yet bounded" groups in `docs/pagination.md`. Every one must be in exactly one group.

- [ ] **Step 3: Check the frontend still works against the bounded API**

Sub-project A requires no frontend change, but that claim should be verified rather than assumed. Start the stack and load the Bookings, Releases, Deployments and Infrastructure pages.

```bash
docker-compose up -d
cd backend && uvicorn app.main:app --reload   # separate terminal
cd frontend && npm run dev                     # separate terminal
```

Expected: every list page renders as before. Any page showing fewer rows than the database holds means an endpoint's default is truncating a real page — record it, as it becomes a sub-project C input.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u github feature/pagination-sweep
gh pr create --repo pjgross/envmgr --base main \
  --title "feat(api): bound the remaining growth-bearing list endpoints" \
  --body "$(cat <<'BODY'
Sub-project A of the pagination programme. Spec:
docs/superpowers/specs/2026-07-30-pagination-sweep-design.md

Bounds the list endpoints that can be bounded mechanically. Backward
compatible throughout: endpoints still return bare JSON arrays, the total is
header-only, and the two endpoints with their own limit contracts keep them.

Also fixes a latent bug in the three endpoints bounded previously — all three
sorted on a non-unique column, so LIMIT/OFFSET over them could already return
a row on two pages and omit another. Every bounded endpoint now ends its
ordering with a primary-key tiebreaker.

Out of scope, documented rather than deferred silently:
- RAID and the two /dependencies endpoints need a query restructure first
  (sub-project B).
- The enterprise rollup aggregations stay permanently unbounded — a partial
  rollup is a wrong rollup.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_013QbxUbUk3kgkp5DsUcK3Kt
BODY
)"
```

---

## Self-Review

**Spec coverage.** Every section of the spec maps to a task: primitive changes → Task 1; total ordering → Task 1 (existing endpoints) plus each conversion task; drop-ins → Tasks 3, 4, 5; header-only → Task 6; `fetch_page_rows` conversions → Tasks 7, 8, 10; service extractions → Tasks 9, 10, 11; conformance sweep → Task 2 and incrementally after; paging-over-ties → Task 12; documentation → Task 13.

**Known soft spots**, called out rather than hidden:

1. Several tasks say "confirm the model's required columns before running" for fixture code. The model definitions were not read while writing this plan, so those fixture constructors are the most likely thing to need adjustment. Each such step names the exact `grep` to run first.
2. Task 11's spec item was wrong and is corrected in place: `ReleaseStatusHistory` has no `tenant_id` column, so the proposed defence-in-depth predicate is not possible. The spec has been amended to match.
3. Task 12 Step 4 cannot guarantee the test fails on demand when the tiebreaker is removed; PostgreSQL is permitted to be consistent, not required to be. The step says so rather than asserting a failure that may not occur.
4. The "fix the other callers" steps use `grep` rather than listing call sites, because the caller set was not enumerated for every service. Each names the exact command.
