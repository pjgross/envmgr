# Pagination Sub-project B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure six queries so their filtering happens in SQL rather than in Python, then bound them with the shared pagination primitive.

**Architecture:** Each task moves one endpoint's post-query filtering into the query, then adds a `Page` dependency and `X-Total-Count`. The restructures are: a severity-domain `IN` clause (RAID), a single `OR` query replacing two concatenated ones (both dependency endpoints), a `ROW_NUMBER()` window (versions), a join with `IS DISTINCT FROM` (dependency-alerts), and bounding one list inside a dict response (membership).

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, PostgreSQL + SQLite (dual-engine suite), pytest / pytest-asyncio 1.4.0, `uv`.

Spec: [`docs/superpowers/specs/2026-07-30-pagination-sweep-b-design.md`](../specs/2026-07-30-pagination-sweep-b-design.md)
Branch: `feature/pagination-sweep-b`, branched off `feature/pagination-sweep` (sub-project A, PR #36).

## Global Constraints

- **This sub-project changes which rows come back.** That is the whole point, and it is also the risk. Every task's central deliverable is a **differential test**: seed fixture data covering the enumerated edge cases, compute the expected set with the *old* Python predicate embedded in the test as a reference implementation, and assert the new SQL returns exactly that. A differential test whose fixtures all take the same branch proves nothing.
- **Enrichment after the query is safe to window; filtering is not.** If a restructure leaves any row-dropping logic in Python, the endpoint must not be bounded — stop and report.
- Bounded endpoints keep returning bare JSON arrays and put the total only in `X-Total-Count`. The single exception is `GET /releases/{id}/membership`, which returns a dict; there the header describes its `history` list.
- Services take `page: Optional[Page] = None` and return `(rows, total)`. `page=None` returns everything, so aggregate callers are unaffected.
- **Ordering must be total.** Every bounded query ends in a unique tiebreaker (the primary key). In sub-project A this was shown empirically to matter: with a tiebreaker removed, pagination broke deterministically on PostgreSQL across repeated runs.
- `pagination()` is a **factory** — endpoints write `Depends(pagination())` with parentheses. Use `fetch_page` for scalar selects and `fetch_page_rows` for multi-column selects.
- No `db.commit()` in services — `get_db()` auto-commits. Use `db.flush()`.
- Tenant-scoped queries filter by `tenant_id`; endpoints use `current_user.active_tenant_id` (some files bind it as `user`), never `.tenant_id`.
- **Never fabricate a foreign key id in a test.** SQLite enforces FKs here and ~40 tests once passed while inserting broken rows. Use `backend/tests/factories.py` where a helper exists.
- **`request.getfixturevalue` does not work on async fixtures** under pytest-asyncio 1.4.0 (`RuntimeError: Runner.run() cannot be called from a running event loop`). Pass fixtures as normal test parameters.
- Parent-id-nested endpoints get **targeted tests, not `BOUNDED_ENDPOINTS` rows** — the conformance sweep runs against an empty tenant and these 404 without a real parent.
- **Verification cadence.** Per task: targeted tests on SQLite (seconds). Full dual-engine suite at two checkpoints only — after Task 1 and in Task 8. The full suite is ~6 min on SQLite and ~14 min on PostgreSQL. **Tasks 4 and 5 additionally run their own targeted tests on PostgreSQL**, because the window function and `is_distinct_from` are dialect-sensitive. **Never background a test run** — use a generous foreground timeout; a 14-minute run is expected, not hung.
- Run all commands from `backend/`.

## Verified facts (read from the code — do not re-derive, do not contradict)

| Fact | Source |
|---|---|
| `RaidItem` requires `tenant_id, release_id, item_type, seq, title, status, raised_by, raised_at`; `probability`/`impact`/`review_date` nullable | `app/db/models/raid.py:10` |
| Default `rag_bands`: `green 1–5`, `amber 6–14`, `red 15–25`; stored as unvalidated JSON | `app/services/raid_config_service.py:24` |
| `rag()` returns the **first** band whose `[min,max]` contains severity | `app/services/raid_service.py:52` |
| `SystemDependency` requires `tenant_id, from_system_id, to_system_id, dependency_type`; `UniqueConstraint(from_system_id, to_system_id, tenant_id)` | `app/db/models/dependency.py:41` |
| `DependencyType` values: `api_call, database, message_queue, event, file, other` | `app/db/models/dependency.py` |
| Self-dependencies are rejected — *"A system cannot depend on itself"* / subsystem equivalent | `dependency_service.py:80`, `:275` |
| `ComponentDependency` adds `protocol, port, label`, requires the same core fields with `*_subsystem_id` | `app/db/models/dependency.py:84` |
| `EnvironmentSubSystemVersion` requires `tenant_id, environment_id, subsystem_id, build_identifier, version_label, installed_at` | `app/db/models/version.py:10` |
| `ReleaseDependency` requires `tenant_id, release_id, depends_on_release_id`; `kind` defaults `deploys_after`; `last_dependency_target_date` nullable | `app/db/models/release_dependency.py:10` |
| `ReleaseMembership` requires `tenant_id, enterprise_release_id, project_release_id, state, requested_by, requested_at` | `app/db/models/release_membership.py:33` |
| `Release` requires `tenant_id, name, release_type, lifecycle_template_id, raised_by`; `lifecycle_template_id` is **not nullable** | `app/db/models/release.py:11` |
| `ROW_NUMBER() OVER (PARTITION BY ...)` works on this repo's SQLite (3.50.4) and on PostgreSQL | verified directly |
| `is_distinct_from()` renders `IS NOT` on SQLite, `IS DISTINCT FROM` on PostgreSQL; both available | verified directly |
| Existing release-building helper for RAID tests: `_make_release(db_session, tenant_id, user_id)` | `tests/services/test_raid_service.py:16` |
| Existing test modules: `tests/integration/test_raid_api.py`, `tests/integration/test_dependencies.py`, `tests/integration/test_versions.py`, `tests/services/test_raid_service.py`, `tests/services/test_release_dependency_service.py` | — |

## File Structure

| File | Change |
|---|---|
| `app/services/raid_service.py` | `list_items` filters in SQL; new `_severity_values_for_rag` helper |
| `app/api/v1/raid.py` | `Page` + `set_total_count` |
| `app/services/dependency_service.py` | both list functions become single `OR` queries returning `(rows, total)` |
| `app/api/v1/dependencies.py` | both endpoints bounded; `is_incoming` derived per row |
| `app/services/version_service.py` | `current_only` becomes a `ROW_NUMBER()` window |
| `app/api/v1/environments.py` | versions endpoint bounded |
| `app/services/release_dependency_service.py` | `get_dependency_alerts` becomes a join; N+1 removed |
| `app/api/v1/releases.py` | dependency-alerts endpoint bounded |
| `app/services/enterprise_membership_service.py` | `list_history_for_project` takes a `Page` |
| `app/api/v1/enterprise_memberships.py` | membership view bounds `history` |
| `tests/test_pagination_b.py` | **new** — all differential + bounding tests for B |
| `docs/pagination.md`, `CLAUDE.md` | updated |

---

## Task 1: RAID — move `rag` and `overdue` into SQL

**Files:**
- Modify: `app/services/raid_service.py:223-243`
- Modify: `app/api/v1/raid.py`
- Test: `tests/test_pagination_b.py` (create)

**Interfaces:**
- Produces: `raid_service.list_items(db, release_id, tenant_id, *, item_type=None, status=None, owner_id=None, rag=None, overdue=None, config=None, page=None) -> tuple[list[RaidItem], int]`
- Produces: `raid_service._severity_values_for_rag(cfg: dict, wanted: str) -> list[int]`

- [ ] **Step 1: Write the differential test**

Create `backend/tests/test_pagination_b.py`:

```python
"""Sub-project B: restructured queries, and the differential tests that pin them.

Each restructure moves filtering out of Python and into SQL. The tests below
embed the *old* Python predicate as a reference implementation and assert the
new SQL agrees with it, because a shape test cannot catch a predicate that
returns a subtly different set.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.pagination import MAX_LIMIT, TOTAL_COUNT_HEADER, Page
from app.db.models.lifecycle import LifecycleTemplate
from app.db.models.release import Release
from app.services import raid_config_service, raid_service


async def _make_release(db_session, tenant_id, user_id, name="B-release"):
    """Mirrors tests/services/test_raid_service.py — lifecycle_template_id is NOT nullable."""
    tpl = LifecycleTemplate(
        tenant_id=tenant_id, entity_type="release", name=f"{name}-tpl",
        definition={"states": [], "transitions": [], "field_permissions": {}},
    )
    db_session.add(tpl)
    await db_session.flush()
    rel = Release(
        tenant_id=tenant_id, name=name, release_type="Major", release_kind="project",
        lifecycle_template_id=tpl.id, status="draft", raised_by=user_id,
    )
    db_session.add(rel)
    await db_session.flush()
    return rel


# ── RAID: the reference implementation the SQL must agree with ───────────────

def _old_rag_filter(items, wanted, cfg):
    """Verbatim semantics of the Python filter this task replaces."""
    return [
        i for i in items
        if raid_service.rag(raid_service.severity(i.probability, i.impact), cfg) == wanted
    ]


def _old_overdue_filter(items, now):
    return [
        i for i in items
        if i.review_date and i.review_date < now
        and i.status not in ("closed", "promoted", "met")
    ]


@pytest.mark.asyncio
async def test_rag_filter_in_sql_matches_the_python_it_replaced(db_session, tenant, user):
    """Covers every severity in the domain, plus unset factors."""
    rel = await _make_release(db_session, tenant.id, user.id)
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)

    # one item per (probability, impact) pair, plus two with unset factors
    for p in range(1, 6):
        for i in range(1, 6):
            db_session.add(raid_service.RaidItem(
                tenant_id=tenant.id, release_id=rel.id, item_type="risk",
                seq=p * 10 + i, title=f"p{p}i{i}", status="open",
                raised_by=user.id, raised_at=datetime.now(timezone.utc),
                probability=p, impact=i,
            ))
    db_session.add(raid_service.RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=900,
        title="no-probability", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=None, impact=3,
    ))
    db_session.add(raid_service.RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=901,
        title="no-impact", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=3, impact=None,
    ))
    await db_session.flush()

    all_items, _ = await raid_service.list_items(db_session, rel.id, tenant.id, config=cfg)

    for wanted in ("green", "amber", "red"):
        expected = {i.id for i in _old_rag_filter(all_items, wanted, raid_service._config_dict(cfg))}
        got, total = await raid_service.list_items(
            db_session, rel.id, tenant.id, rag=wanted, config=cfg
        )
        assert {i.id for i in got} == expected, f"{wanted} diverged"
        assert total == len(expected)


@pytest.mark.asyncio
async def test_rag_filter_honours_first_match_when_bands_overlap(db_session, tenant, user):
    """rag_bands has no validation, and rag() resolves by FIRST match.

    An OR-of-BETWEEN translation would wrongly include severity 5 in 'amber'.
    """
    rel = await _make_release(db_session, tenant.id, user.id, name="overlap")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    cfg = await raid_config_service.update_config(
        db_session, tenant.id,
        rag_bands=[
            {"rag": "green", "min": 1, "max": 5},
            {"rag": "amber", "min": 4, "max": 14},   # overlaps green on 4-5
            {"rag": "red", "min": 15, "max": 25},
        ],
    )
    for p, i, label in [(1, 4, "sev4"), (1, 5, "sev5"), (2, 3, "sev6")]:
        db_session.add(raid_service.RaidItem(
            tenant_id=tenant.id, release_id=rel.id, item_type="risk",
            seq=p * 100 + i, title=label, status="open", raised_by=user.id,
            raised_at=datetime.now(timezone.utc), probability=p, impact=i,
        ))
    await db_session.flush()

    green, _ = await raid_service.list_items(db_session, rel.id, tenant.id, rag="green", config=cfg)
    amber, _ = await raid_service.list_items(db_session, rel.id, tenant.id, rag="amber", config=cfg)

    # severities 4 and 5 match green first, so amber must NOT claim them
    assert {i.title for i in green} == {"sev4", "sev5"}
    assert {i.title for i in amber} == {"sev6"}


@pytest.mark.asyncio
async def test_unknown_rag_label_matches_nothing(db_session, tenant, user):
    """An empty severity set must become false(), not a skipped filter."""
    rel = await _make_release(db_session, tenant.id, user.id, name="unknown-rag")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    db_session.add(raid_service.RaidItem(
        tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=1,
        title="A", status="open", raised_by=user.id,
        raised_at=datetime.now(timezone.utc), probability=3, impact=3,
    ))
    await db_session.flush()

    got, total = await raid_service.list_items(
        db_session, rel.id, tenant.id, rag="chartreuse", config=cfg
    )
    assert got == []
    assert total == 0


@pytest.mark.asyncio
async def test_overdue_filter_in_sql_matches_the_python_it_replaced(db_session, tenant, user):
    rel = await _make_release(db_session, tenant.id, user.id, name="overdue")
    cfg = await raid_config_service.get_or_seed_config(db_session, tenant.id)
    now = datetime.now(timezone.utc)
    past, future = now - timedelta(days=3), now + timedelta(days=3)

    rows = [
        ("past-open", past, "open"),
        ("past-closed", past, "closed"),
        ("past-promoted", past, "promoted"),
        ("past-met", past, "met"),
        ("future-open", future, "open"),
        ("none-open", None, "open"),
    ]
    for n, (title, review, status) in enumerate(rows, start=1):
        db_session.add(raid_service.RaidItem(
            tenant_id=tenant.id, release_id=rel.id, item_type="risk", seq=n,
            title=title, status=status, raised_by=user.id, raised_at=now,
            review_date=review,
        ))
    await db_session.flush()

    all_items, _ = await raid_service.list_items(db_session, rel.id, tenant.id, config=cfg)
    expected = {i.id for i in _old_overdue_filter(all_items, datetime.now(timezone.utc))}

    got, total = await raid_service.list_items(
        db_session, rel.id, tenant.id, overdue=True, config=cfg
    )
    assert {i.id for i in got} == expected
    assert {i.title for i in got} == {"past-open"}
    assert total == len(expected)
```

Add `from app.db.models.raid import RaidItem` and reference it directly rather than via `raid_service.RaidItem` if the service does not re-export it — check before running.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q`
Expected: FAIL — `list_items` returns a list, not a tuple, so unpacking raises.

- [ ] **Step 3: Restructure `list_items`**

Replace `app/services/raid_service.py:223-243`:

```python
def _severity_values_for_rag(cfg: dict, wanted: str) -> list[int]:
    """Severity scores that map to `wanted`, per the tenant's own bands.

    Evaluating the real rag() over the whole (bounded) severity domain rather
    than translating band ranges into SQL preserves first-match semantics —
    including for overlapping bands, which nothing validates against.
    """
    p = len(cfg.get("probability_scale") or [])
    i = len(cfg.get("impact_scale") or [])
    return [s for s in range(1, p * i + 1) if rag(s, cfg) == wanted]


async def list_items(db: AsyncSession, release_id: int, tenant_id: int, *,
                     item_type=None, status=None, owner_id=None, rag=None,
                     overdue=None, config=None, page: Optional[Page] = None):
    stmt = select(RaidItem).where(
        RaidItem.tenant_id == tenant_id, RaidItem.release_id == release_id,
        RaidItem.deleted_at.is_(None))
    if item_type:
        stmt = stmt.where(RaidItem.item_type == item_type)
    if status:
        stmt = stmt.where(RaidItem.status == status)
    if owner_id:
        stmt = stmt.where(RaidItem.owner_id == owner_id)
    if rag is not None and config is not None:
        # severity is probability * impact; NULL in either factor propagates,
        # and NULL IN (...) is NULL, so unset items are excluded exactly as
        # severity()->None->rag()->None did.
        values = _severity_values_for_rag(_config_dict(config), rag)
        stmt = stmt.where(
            (RaidItem.probability * RaidItem.impact).in_(values) if values else false()
        )
    if overdue:
        stmt = stmt.where(
            RaidItem.review_date.isnot(None),
            RaidItem.review_date < datetime.now(timezone.utc),
            RaidItem.status.notin_(("closed", "promoted", "met")),
        )
    stmt = stmt.order_by(RaidItem.item_type, RaidItem.seq, RaidItem.id)
    return await fetch_page(db, stmt, page)
```

Note the parameter `rag` shadows the module-level `rag()` function — that is why the original used `globals()["rag"]`. `_severity_values_for_rag` calls `rag()` from module scope where there is no shadowing, so the shadowing problem disappears. Do not reintroduce a `globals()` lookup.

Add imports: `from sqlalchemy import false`, `from typing import Optional`, `from app.core.pagination import Page, fetch_page`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q`
Expected: PASS — 4 tests.

- [ ] **Step 5: Fix every caller**

Run: `cd backend && grep -rn "list_items(" app/ tests/ scripts/ | grep -v "def list_items"`

`raid_service.summary` is a known caller and aggregates the whole release — it must keep `page=None` and unpack `items, _ = await list_items(...)`. Unpack at every other site too.

- [ ] **Step 6: Bound the endpoint**

In `app/api/v1/raid.py`, add `from app.core.pagination import Page, pagination, set_total_count` and `Response` from `fastapi`, then add `response: Response` and `page: Page = Depends(pagination())` to the `GET /{release_id}/raid` endpoint, pass `page=page`, unpack `(rows, total)`, and call `set_total_count(response, total)` before building the response.

Read the endpoint first — it loads the tenant RAID config and maps rows through `to_read`. That mapping is enrichment and stays unchanged.

- [ ] **Step 7: Add a bounding test**

Append to `tests/test_pagination_b.py`:

```python
@pytest.mark.asyncio
async def test_raid_endpoint_is_bounded(client, auth_headers, db_session, test_tenant, test_user):
    rel = await _make_release(db_session, test_tenant.id, test_user.id, name="api-raid")
    await raid_config_service.get_or_seed_config(db_session, test_tenant.id)
    for n in range(3):
        db_session.add(RaidItem(
            tenant_id=test_tenant.id, release_id=rel.id, item_type="risk", seq=n + 1,
            title=f"item-{n}", status="open", raised_by=test_user.id,
            raised_at=datetime.now(timezone.utc), probability=2, impact=2,
        ))
    await db_session.commit()

    url = f"/api/v1/releases/{rel.id}/raid"
    response = await client.get(url, headers=auth_headers)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
    assert int(response.headers[TOTAL_COUNT_HEADER]) == 3

    windowed = await client.get(f"{url}?limit=2", headers=auth_headers)
    assert len(windowed.json()) == 2
    assert int(windowed.headers[TOTAL_COUNT_HEADER]) == 3

    over = await client.get(f"{url}?limit={MAX_LIMIT + 1}", headers=auth_headers)
    assert over.status_code == 422
```

Confirm the actual route path with `grep -n '@router.get' backend/app/api/v1/raid.py` and how it is mounted in `app/main.py` before asserting on the URL.

- [ ] **Step 8: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/services/test_raid_service.py tests/services/test_raid_summary.py tests/services/test_raid_scoring.py tests/integration/test_raid_api.py tests/integration/test_raid_rollup.py -q`
Expected: PASS. Record the count.

- [ ] **Step 9: CHECKPOINT — full dual-engine suite**

The RAID change alters a filter's semantics and `raid_service` is used by the enterprise rollup, so this one gets a full run rather than waiting for the end.

Run: `cd backend && uv run pytest -q` — expect ~952 passed, 1 skipped. Allow 8 minutes, foreground.
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` — allow 20 minutes, foreground. Do not background these.

- [ ] **Step 10: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(raid): filter rag and overdue in SQL, and bound the endpoint

rag() resolves by first match and rag_bands is unvalidated JSON, so an
OR-of-BETWEEN translation would silently diverge for overlapping bands.
Instead the bounded severity domain is enumerated and the real rag() is
evaluated over it, which makes the translation correct by construction."
```

---

## Task 2: System dependencies — one `OR` query

**Files:**
- Modify: `app/services/dependency_service.py:28-70`
- Modify: `app/api/v1/dependencies.py:53-97`
- Test: `tests/test_pagination_b.py`

**Interfaces:**
- Produces: `dependency_service.list_system_dependencies(db, system_id, tenant_id, page=None) -> tuple[list[SystemDependency], int]` — **no longer returns `(outgoing, incoming)`**. This is a breaking signature change; every caller must be found.

- [ ] **Step 1: Write the differential test**

Append to `tests/test_pagination_b.py`:

```python
# ── System dependencies ──────────────────────────────────────────────────────

async def _make_system(db_session, tenant_id, name):
    from app.db.models.system import System
    s = System(tenant_id=tenant_id, name=name)
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.mark.asyncio
async def test_system_dependencies_return_same_rows_and_order_as_two_queries(
    db_session, tenant
):
    """The OR query must reproduce the concatenation exactly: same rows, and
    outgoing-then-incoming grouping preserved."""
    from app.db.models.dependency import DependencyType, SystemDependency
    from app.services import dependency_service

    me = await _make_system(db_session, tenant.id, "me")
    a = await _make_system(db_session, tenant.id, "a")
    b = await _make_system(db_session, tenant.id, "b")

    out1 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=a.id, dependency_type=DependencyType.API_CALL)
    out2 = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                            to_system_id=b.id, dependency_type=DependencyType.DATABASE)
    inc1 = SystemDependency(tenant_id=tenant.id, from_system_id=a.id,
                            to_system_id=me.id, dependency_type=DependencyType.EVENT)
    for d in (out1, out2, inc1):
        db_session.add(d)
    await db_session.flush()

    rows, total = await dependency_service.list_system_dependencies(
        db_session, me.id, tenant.id
    )

    # Reference: what the two-query version returned, concatenated.
    expected_ids = [out1.id, out2.id, inc1.id]
    assert [r.id for r in rows] == expected_ids, "grouping or membership changed"
    assert total == 3


@pytest.mark.asyncio
async def test_system_dependencies_handle_one_sided_cases(db_session, tenant):
    from app.db.models.dependency import DependencyType, SystemDependency
    from app.services import dependency_service

    me = await _make_system(db_session, tenant.id, "solo")
    other = await _make_system(db_session, tenant.id, "other")

    # outgoing only
    d = SystemDependency(tenant_id=tenant.id, from_system_id=me.id,
                         to_system_id=other.id, dependency_type=DependencyType.API_CALL)
    db_session.add(d)
    await db_session.flush()
    rows, total = await dependency_service.list_system_dependencies(db_session, me.id, tenant.id)
    assert [r.id for r in rows] == [d.id] and total == 1

    # and from the other side it is incoming only
    rows, total = await dependency_service.list_system_dependencies(db_session, other.id, tenant.id)
    assert [r.id for r in rows] == [d.id] and total == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k system_dependencies`
Expected: FAIL — the service still returns a 2-tuple of lists, so `[r.id for r in rows]` iterates the outgoing list and `total` is the incoming list.

- [ ] **Step 3: Restructure the service**

Replace `list_system_dependencies` in `app/services/dependency_service.py`:

```python
async def list_system_dependencies(
    db: AsyncSession, system_id: int, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[SystemDependency], int]:
    """Dependencies touching `system_id`, outgoing first then incoming.

    One OR query rather than two concatenated ones, so the result can be
    windowed. A row can only match both sides via a self-dependency, which
    create_system_dependency rejects, so no row is duplicated. The CASE
    reproduces the previous outgoing-then-incoming grouping and, with the
    primary key appended, makes the ordering total.
    """
    await get_system(db, system_id, tenant_id)

    query = (
        select(SystemDependency)
        .where(
            SystemDependency.tenant_id == tenant_id,
            or_(
                SystemDependency.from_system_id == system_id,
                SystemDependency.to_system_id == system_id,
            ),
        )
        .options(
            selectinload(SystemDependency.to_system),
            selectinload(SystemDependency.from_system),
        )
        .order_by(
            case((SystemDependency.to_system_id == system_id, 1), else_=0),
            SystemDependency.id,
        )
    )
    return await fetch_page(db, query, page)
```

Add imports: `from sqlalchemy import case, or_`, `from typing import Optional`, `from app.core.pagination import Page, fetch_page`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k system_dependencies`
Expected: PASS.

- [ ] **Step 5: Update the endpoint**

Replace the endpoint body in `app/api/v1/dependencies.py:57`:

```python
@router.get(
    "/systems/{system_id}/dependencies",
    response_model=list[SystemDependencyResponse],
)
async def list_system_dependencies(
    system_id: int,
    response: Response,
    page: Page = Depends(pagination()),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    rows, total = await dependency_service.list_system_dependencies(
        db, system_id, current_user.active_tenant_id, page=page
    )
    set_total_count(response, total)
    return [
        SystemDependencyResponse(
            id=dep.id,
            from_system_id=dep.from_system_id,
            to_system_id=dep.to_system_id,
            dependency_type=dep.dependency_type,
            direction=dep.direction,
            source=dep.source,
            tenant_id=dep.tenant_id,
            to_system=dep.to_system,
            from_system=dep.from_system,
            is_incoming=dep.to_system_id == system_id,
        )
        for dep in rows
    ]
```

`is_incoming` is now derived per row, matching what `_build_comp_dep_response` already does. Add `Response` and the pagination imports.

- [ ] **Step 6: Fix every caller**

Run: `cd backend && grep -rn "list_system_dependencies(" app/ tests/ scripts/ | grep -v "def list_system_dependencies"`

This signature changed shape (`(outgoing, incoming)` → `(rows, total)`), so **every** caller breaks — including any that unpacked two lists. Read each and rewrite it against the new shape rather than mechanically renaming.

- [ ] **Step 7: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/integration/test_dependencies.py -q` plus any other module found by `grep -rl "dependencies" tests/`.
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound system dependencies via a single OR query

The two queries differed only in from_/to_, so one OR returns the same rows —
self-dependencies are rejected, so nothing matches both sides. A CASE in the
ORDER BY preserves the outgoing-then-incoming grouping."
```

---

## Task 3: Component dependencies — one `OR` query

Structurally identical to Task 2, on subsystems.

**Files:**
- Modify: `app/services/dependency_service.py:218-260`
- Modify: `app/api/v1/dependencies.py:175-192`
- Test: `tests/test_pagination_b.py`

**Interfaces:**
- Produces: `dependency_service.list_component_dependencies(db, subsystem_id, tenant_id, page=None) -> tuple[list[ComponentDependency], int]`

- [ ] **Step 1: Write the differential test**

Append to `tests/test_pagination_b.py`:

```python
# ── Component dependencies ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_component_dependencies_return_same_rows_and_order(db_session, tenant):
    from app.db.models.dependency import ComponentDependency, DependencyType
    from app.services import dependency_service
    from tests.factories import ensure_subsystem

    me = await ensure_subsystem(db_session, tenant.id, name="dep-me")
    other = await ensure_subsystem(db_session, tenant.id, name="dep-other")

    # INSERT THE INCOMING ROW FIRST so it gets the LOWER autoincrement id.
    # If outgoing rows are created first their ids already sort
    # outgoing-then-incoming, and the test would still pass with the CASE
    # removed — i.e. it would not actually guard the grouping. Creating the
    # incoming row first makes the CASE load-bearing: a plain ORDER BY id
    # would put it first and fail this assertion.
    inc = ComponentDependency(tenant_id=tenant.id, from_subsystem_id=other.id,
                              to_subsystem_id=me.id,
                              dependency_type=DependencyType.DATABASE)
    db_session.add(inc)
    await db_session.flush()

    out = ComponentDependency(tenant_id=tenant.id, from_subsystem_id=me.id,
                              to_subsystem_id=other.id,
                              dependency_type=DependencyType.API_CALL)
    db_session.add(out)
    await db_session.flush()

    assert inc.id < out.id, "fixture must give the incoming row the lower id"

    rows, total = await dependency_service.list_component_dependencies(
        db_session, me.id, tenant.id
    )
    # outgoing first despite having the HIGHER id — this is the grouping check
    assert [r.id for r in rows] == [out.id, inc.id]
    assert total == 2
```

Note the factory signatures differ and are easy to conflate:
`ensure_subsystem(db, tenant_id, name="test-subsystem")` takes a **name** and returns an
existing row if one already has that name, whereas `ensure_environment(db, tenant_id, slot=1)`
takes a **slot**. Two distinct subsystems therefore need two distinct names.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k component_dependencies`
Expected: FAIL.

- [ ] **Step 3: Restructure the service**

```python
async def list_component_dependencies(
    db: AsyncSession, subsystem_id: int, tenant_id: int, page: Optional[Page] = None
) -> tuple[list[ComponentDependency], int]:
    """As list_system_dependencies, for subsystems. Self-dependencies are
    rejected by create_component_dependency, so the OR cannot duplicate a row."""
    await _get_subsystem(db, subsystem_id, tenant_id)

    query = (
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            or_(
                ComponentDependency.from_subsystem_id == subsystem_id,
                ComponentDependency.to_subsystem_id == subsystem_id,
            ),
        )
        .options(
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
        .order_by(
            case((ComponentDependency.to_subsystem_id == subsystem_id, 1), else_=0),
            ComponentDependency.id,
        )
    )
    return await fetch_page(db, query, page)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k component_dependencies`
Expected: PASS.

- [ ] **Step 5: Update the endpoint**

`app/api/v1/dependencies.py:179` — add `response: Response` and `page: Page = Depends(pagination())`, unpack, set the header, and return `[_build_comp_dep_response(dep, subsystem_id) for dep in rows]`. `_build_comp_dep_response` already derives `is_incoming` from the row, so it needs no change.

- [ ] **Step 6: Fix every caller**

Run: `cd backend && grep -rn "list_component_dependencies(" app/ tests/ scripts/ | grep -v "def list_component_dependencies"`

- [ ] **Step 7: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/integration/test_dependencies.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound component dependencies via a single OR query"
```

---

## Task 4: Versions — `current_only` becomes a window function

**Files:**
- Modify: `app/services/version_service.py:82-118`
- Modify: `app/api/v1/environments.py:277-287`
- Test: `tests/test_pagination_b.py`

**Interfaces:**
- Produces: `version_service.list_versions(db, env_id, tenant_id, current_only=False, page=None) -> tuple[list[EnvironmentSubSystemVersion], int]`

- [ ] **Step 1: Write the differential test**

```python
# ── Versions ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_current_only_returns_one_row_per_subsystem(db_session, tenant):
    """The Python dedup kept the first row per subsystem under an ORDER BY that
    did not break ties; the window function makes that deterministic. So this
    asserts the invariant (one row per subsystem, and it is the latest), not a
    specific winner for the tied case.
    """
    from app.db.models.version import EnvironmentSubSystemVersion
    from app.services import version_service
    from tests.factories import ensure_environment, ensure_subsystem

    env = await ensure_environment(db_session, tenant.id)
    sub_a = await ensure_subsystem(db_session, tenant.id, name="ver-a")
    sub_b = await ensure_subsystem(db_session, tenant.id, name="ver-b")
    now = datetime.now(timezone.utc)

    def _v(sub_id, label, installed):
        return EnvironmentSubSystemVersion(
            tenant_id=tenant.id, environment_id=env.id, subsystem_id=sub_id,
            build_identifier=f"build-{label}", version_label=label,
            installed_at=installed,
        )

    db_session.add(_v(sub_a.id, "a-old", now - timedelta(days=2)))
    db_session.add(_v(sub_a.id, "a-new", now))
    db_session.add(_v(sub_b.id, "b-only", now - timedelta(days=1)))
    await db_session.flush()

    all_rows, all_total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=False
    )
    assert all_total == 3

    current, total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=True
    )
    assert total == 2
    by_sub = {v.subsystem_id: v.version_label for v in current}
    assert by_sub == {sub_a.id: "a-new", sub_b.id: "b-only"}


@pytest.mark.asyncio
async def test_current_only_picks_exactly_one_row_when_timestamps_tie(db_session, tenant):
    """installed_at is not unique. The old code's winner was undefined; the new
    one is deterministic. Assert the invariant, not which row wins."""
    from app.db.models.version import EnvironmentSubSystemVersion
    from app.services import version_service
    from tests.factories import ensure_environment, ensure_subsystem

    env = await ensure_environment(db_session, tenant.id)
    sub = await ensure_subsystem(db_session, tenant.id, name="ver-tied")
    same = datetime.now(timezone.utc)

    for label in ("tied-1", "tied-2"):
        db_session.add(EnvironmentSubSystemVersion(
            tenant_id=tenant.id, environment_id=env.id, subsystem_id=sub.id,
            build_identifier=f"b-{label}", version_label=label, installed_at=same,
        ))
    await db_session.flush()

    current, total = await version_service.list_versions(
        db_session, env.id, tenant.id, current_only=True
    )
    assert total == 1
    assert len(current) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k current_only`
Expected: FAIL — returns a list, not a tuple.

- [ ] **Step 3: Restructure the service**

```python
async def list_versions(
    db: AsyncSession,
    env_id: int,
    tenant_id: int,
    current_only: bool = False,
    page: Optional[Page] = None,
) -> tuple[list[EnvironmentSubSystemVersion], int]:
    """Version history for an environment.

    With current_only, the latest row per subsystem. That was a Python dedup
    over every row; it is now a ROW_NUMBER() window, so the result can be
    windowed. installed_at is not unique, so id DESC breaks ties inside the
    partition — the previous winner for a tie was whichever row the query
    happened to return first, which was undefined.
    """
    await get_environment(db, env_id, tenant_id)

    base = select(EnvironmentSubSystemVersion).where(
        EnvironmentSubSystemVersion.environment_id == env_id,
        EnvironmentSubSystemVersion.tenant_id == tenant_id,
    )

    if not current_only:
        query = base.options(
            selectinload(EnvironmentSubSystemVersion.subsystem)
        ).order_by(
            EnvironmentSubSystemVersion.subsystem_id,
            EnvironmentSubSystemVersion.installed_at.desc(),
            EnvironmentSubSystemVersion.id,
        )
        return await fetch_page(db, query, page)

    ranked = base.add_columns(
        func.row_number()
        .over(
            partition_by=EnvironmentSubSystemVersion.subsystem_id,
            order_by=(
                EnvironmentSubSystemVersion.installed_at.desc(),
                EnvironmentSubSystemVersion.id.desc(),
            ),
        )
        .label("rn")
    ).subquery()

    entity = aliased(EnvironmentSubSystemVersion, ranked)
    query = (
        select(entity)
        .where(ranked.c.rn == 1)
        .options(selectinload(entity.subsystem))
        .order_by(ranked.c.subsystem_id, ranked.c.id)
    )
    return await fetch_page(db, query, page)
```

Add imports: `from sqlalchemy import func`, `from sqlalchemy.orm import aliased`, `from typing import Optional`, `from app.core.pagination import Page, fetch_page`.

If `add_columns` on a `select(Entity)` does not produce a usable subquery for `aliased`, fall back to building the ranked select explicitly with `select(EnvironmentSubSystemVersion, func.row_number()...)`. Verify by running the test, not by reasoning.

- [ ] **Step 4: Run to verify it passes on BOTH engines**

Window functions are dialect-sensitive, so this task does not wait for the checkpoint.

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k current_only`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_pagination_b.py -q -k current_only`
Expected: PASS on both.

- [ ] **Step 5: Bound the endpoint and fix callers**

`app/api/v1/environments.py:277` — add `response: Response` and `page: Page = Depends(pagination())`, pass `page=page`, unpack, set the header, keep the `VersionResponse.from_orm_with_name` mapping.

Run: `cd backend && grep -rn "list_versions(" app/ tests/ scripts/ | grep -v "def list_versions"` and unpack at every site.

- [ ] **Step 6: Run targeted tests on both engines**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/integration/test_versions.py -q`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_pagination_b.py tests/integration/test_versions.py -q`
Expected: PASS on both.

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound environment versions; current_only becomes a window

The latest-per-subsystem dedup ran in Python over every row. ROW_NUMBER()
moves it into SQL so the result can be windowed, and id DESC inside the
partition makes the tie-break deterministic where it previously was not."
```

---

## Task 5: Dependency alerts — join away the filter and the N+1

**Files:**
- Modify: `app/services/release_dependency_service.py:137-190`
- Modify: `app/api/v1/releases.py` (the `/{release_id}/dependency-alerts` endpoint)
- Test: `tests/test_pagination_b.py`

**Interfaces:**
- Produces: `release_dependency_service.get_dependency_alerts(db, release_id, tenant_id, page=None) -> tuple[list[ReleaseDependencyAlert], int]`

- [ ] **Step 1: Write the differential test**

```python
# ── Dependency alerts ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dependency_alerts_match_the_python_filter_they_replaced(
    db_session, tenant, user
):
    """Covers: unchanged dates (skip), both-None (skip), one-None (alert),
    changed (alert), and a soft-deleted target release (skip)."""
    from app.db.models.release_dependency import ReleaseDependency
    from app.services import release_dependency_service

    rel = await _make_release(db_session, tenant.id, user.id, name="alerts-parent")
    now = datetime.now(timezone.utc)

    async def _dep(name, target_date, prior, deleted=False):
        target = await _make_release(db_session, tenant.id, user.id, name=name)
        target.target_date = target_date
        if deleted:
            target.deleted_at = now
        d = ReleaseDependency(
            tenant_id=tenant.id, release_id=rel.id,
            depends_on_release_id=target.id, kind="deploys_after",
            last_dependency_target_date=prior,
        )
        db_session.add(d)
        await db_session.flush()
        return d

    unchanged = await _dep("unchanged", now, now)
    both_none = await _dep("both-none", None, None)
    now_set = await _dep("now-set", now, None)
    now_gone = await _dep("now-gone", None, now)
    shifted = await _dep("shifted", now + timedelta(days=5), now)
    deleted = await _dep("deleted-target", now + timedelta(days=5), now, deleted=True)

    alerts, total = await release_dependency_service.get_dependency_alerts(
        db_session, rel.id, tenant.id
    )

    alerted_dep_ids = {a.dependency_id for a in alerts}
    assert alerted_dep_ids == {now_set.id, now_gone.id, shifted.id}
    assert unchanged.id not in alerted_dep_ids
    assert both_none.id not in alerted_dep_ids
    assert deleted.id not in alerted_dep_ids, "soft-deleted target must not alert"
    assert total == 3
```

`ReleaseDependencyAlert` (`app/api/v1/schemas/release_dependency.py:25`) has fields
`dependency_id, depends_on_release_id, depends_on_name, prior_target_date,
current_target_date, diff_days` — verified, so `a.dependency_id` above is correct.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k dependency_alerts`
Expected: FAIL.

- [ ] **Step 3: Restructure the service**

```python
async def get_dependency_alerts(
    db: AsyncSession,
    release_id: int,
    tenant_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseDependencyAlert], int]:
    """Dependencies whose target release's date has shifted.

    Previously this fetched every dependency and issued another query per row
    for its target release, then skipped the ones that were missing or
    unchanged — a filter after the query, and an N+1. The join reproduces
    'target release exists and is not deleted'; is_distinct_from reproduces
    'current != prior', including the both-NULL case the old code also skipped.
    """
    query = (
        select(ReleaseDependency, Release)
        .join(
            Release,
            and_(
                Release.id == ReleaseDependency.depends_on_release_id,
                Release.tenant_id == tenant_id,
                Release.deleted_at.is_(None),
            ),
        )
        .where(
            ReleaseDependency.release_id == release_id,
            ReleaseDependency.tenant_id == tenant_id,
            Release.target_date.is_distinct_from(
                ReleaseDependency.last_dependency_target_date
            ),
        )
        .order_by(ReleaseDependency.id)
    )
    rows, total = await fetch_page_rows(db, query, page)

    alerts: list[ReleaseDependencyAlert] = []
    for dep, dep_release in rows:
        current = dep_release.target_date
        prior = dep.last_dependency_target_date
        if current is not None and prior is not None:
            diff_days = (current.replace(tzinfo=None) - prior.replace(tzinfo=None)).days
        elif current is not None:
            diff_days = 1
        else:
            diff_days = -1
        alerts.append(...)  # keep the existing construction, with diff_days
    return alerts, total
```

Preserve the existing `ReleaseDependencyAlert(...)` construction verbatim — only its surroundings change. Note the old `else: continue  # both None` branch is now unreachable because the `is_distinct_from` predicate already excluded that case; drop it rather than leaving dead code.

Add imports: `from sqlalchemy import and_`, `from app.core.pagination import Page, fetch_page_rows`.

- [ ] **Step 4: Run to verify it passes on BOTH engines**

`is_distinct_from` renders differently per dialect, so verify both now.

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k dependency_alerts`
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/test_pagination_b.py -q -k dependency_alerts`
Expected: PASS on both.

- [ ] **Step 5: Bound the endpoint and fix callers**

Find the endpoint with `grep -n "dependency-alerts" -A 12 backend/app/api/v1/releases.py`. Add `response: Response`, `page: Page = Depends(pagination())`, pass `page=page`, unpack, set the header.

Run: `cd backend && grep -rn "get_dependency_alerts(" app/ tests/ scripts/ | grep -v "def get_dependency_alerts"`

- [ ] **Step 6: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/services/test_release_dependency_service.py tests/test_releases_api.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound dependency alerts; join away the filter and the N+1

The alert filter ran in Python after a query that issued one further query per
dependency. A join plus is_distinct_from expresses both, so the endpoint can be
windowed and the per-row query disappears."
```

---

## Task 6: Membership view — bound the `history` list

**Files:**
- Modify: `app/services/enterprise_membership_service.py:362-376`
- Modify: `app/api/v1/enterprise_memberships.py:207-233`
- Test: `tests/test_pagination_b.py`

**Interfaces:**
- Produces: `enterprise_membership_service.list_history_for_project(db, *, user, project_release_id, page=None) -> tuple[list[ReleaseMembership], int]`

- [ ] **Step 1: Understand what must NOT change**

`list_history_for_project` returns **every** membership for the project, including the accepted one, and the endpoint prepends `current` separately — so an accepted membership appears both as `current` and inside `history`. That is existing behaviour. **Preserve it.** Changing it is a client-visible semantic change unrelated to pagination and would make the differential test meaningless. It is recorded as a follow-up in the spec.

- [ ] **Step 2: Write the test**

```python
# ── Membership view ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_membership_view_bounds_history_and_preserves_duplication(
    client, auth_headers, db_session, test_tenant, test_user
):
    """history includes the accepted membership that also appears as `current`.
    That duplication is pre-existing and deliberately preserved here."""
    from app.db.models.release_membership import ReleaseMembership

    ent = await _make_release(db_session, test_tenant.id, test_user.id, name="ent")
    proj = await _make_release(db_session, test_tenant.id, test_user.id, name="proj")
    now = datetime.now(timezone.utc)

    db_session.add(ReleaseMembership(
        tenant_id=test_tenant.id, enterprise_release_id=ent.id,
        project_release_id=proj.id, state="accepted",
        requested_by=test_user.id, requested_at=now,
    ))
    db_session.add(ReleaseMembership(
        tenant_id=test_tenant.id, enterprise_release_id=ent.id,
        project_release_id=proj.id, state="rejected",
        requested_by=test_user.id, requested_at=now - timedelta(days=1),
    ))
    await db_session.commit()

    response = await client.get(
        f"/api/v1/releases/{proj.id}/membership", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["current"] is not None
    assert len(body["history"]) == 2, "accepted membership still appears in history"
    assert int(response.headers[TOTAL_COUNT_HEADER]) == 2
```

`MembershipState` (`app/db/models/release_membership.py:18`) is
`pending_request, accepted, rejected, withdrawn, removed` — verified, so the literals
above are valid. Note the partial unique index covers `state IN ('pending_request',
'accepted')`, so the fixture must not create two accepted rows for one project; the
second row above is `rejected` for exactly that reason.

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && uv run pytest tests/test_pagination_b.py -q -k membership_view`
Expected: FAIL on the missing `X-Total-Count`.

- [ ] **Step 4: Add the page parameter to the service**

```python
async def list_history_for_project(
    db: AsyncSession,
    *,
    user: User,
    project_release_id: int,
    page: Optional[Page] = None,
) -> tuple[list[ReleaseMembership], int]:
    stmt = (
        select(ReleaseMembership)
        .where(
            ReleaseMembership.project_release_id == project_release_id,
            ReleaseMembership.tenant_id == user.active_tenant_id,
        )
        .order_by(ReleaseMembership.requested_at.desc(), ReleaseMembership.id)
    )
    return await fetch_page(db, stmt, page)
```

- [ ] **Step 5: Bound the endpoint**

In `app/api/v1/enterprise_memberships.py`, add `response: Response` and `page: Page = Depends(pagination())` to `project_membership_view`, unpack `history, history_total`, and call `set_total_count(response, history_total)`. Keep the rest of the body — the `current` lookup, the combined `_hydrate_reads` call, and the `reads[0]` / `reads[1:]` split — exactly as it is.

The response stays a dict. `X-Total-Count` describes `history`, and the docs task must say so.

- [ ] **Step 6: Fix every caller**

Run: `cd backend && grep -rn "list_history_for_project(" app/ tests/ scripts/ | grep -v "def list_history_for_project"`

- [ ] **Step 7: Run targeted tests**

Run: `cd backend && uv run pytest tests/test_pagination_b.py tests/services/test_enterprise_membership_service.py tests/integration/test_enterprise_memberships_api.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app backend/tests
git commit -m "feat(api): bound the history list in the project membership view

The response is a dict, not an array, so X-Total-Count describes history —
the only part that grows. The accepted membership appearing in both current
and history is pre-existing and deliberately preserved."
```

---

## Task 7: Documentation

**Files:**
- Modify: `docs/pagination.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Re-derive the counts**

Run:
```bash
cd backend && grep -rn -B3 'response_model=list\[' app/api/v1 | grep -v __pycache__ | grep -E '\.get\(' | wc -l
cd backend && grep -rn "set_total_count" app/api/v1/*.py | grep -v "^.*import" | wc -l
```
Use the real numbers. Sub-project A left 22 bounded of 51 list endpoints; B adds five of those plus `membership`, which is not in the `list[...]` count because it returns a dict. State the new figures explicitly.

- [ ] **Step 2: Move the six into the bounded table**

In `docs/pagination.md`, move `raid`, both `dependencies` endpoints, `versions`, `dependency-alerts` and `membership` out of their current groups into the bounded table, each with its service and cap.

- [ ] **Step 3: Record that the blocked group is now empty**

The "blocked on a query restructure" section should say so plainly rather than being silently deleted — a future reader benefits from knowing the category existed and was cleared, and by what means. One line per restructure: severity-domain `IN`, `OR` query, `ROW_NUMBER()` window, join with `IS DISTINCT FROM`.

- [ ] **Step 4: Document the membership header's subject**

`X-Total-Count` on `GET /releases/{id}/membership` describes its `history` list, not a top-level array. Say so explicitly — a header whose subject is ambiguous is worse than no header.

- [ ] **Step 5: Record the follow-ups**

Two, neither done here:
- the accepted membership appears in both `current` and `history`;
- `/releases/calendar` and `/timeline` still filter `target_date` in Python after a hardcoded `limit=500`.

- [ ] **Step 6: Update `CLAUDE.md`**

Correct its bounded/unbounded counts to match, and note that the blocked-on-restructure group is now empty.

- [ ] **Step 7: Verify every claim**

For each endpoint asserted bounded, confirm with `grep -n "Depends(pagination(" backend/app/api/v1/<file>.py`. Report which claims you checked and how.

- [ ] **Step 8: Commit**

```bash
git add docs/pagination.md CLAUDE.md
git commit -m "docs: record sub-project B — the blocked group is now empty"
```

---

## Task 8: Final verification and PR

- [ ] **Step 1: Full suite on both engines**

Run: `cd backend && uv run pytest -q` — allow 8 minutes, foreground.
Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q` — allow 20 minutes, foreground.

Record both totals. Do not claim completion without them.

- [ ] **Step 2: Confirm no post-query filtering remains**

For each of the six endpoints, re-read the service and endpoint and confirm nothing drops or merges rows after the query. This is the property the whole sub-project exists to establish, and it is the one thing no test asserts directly.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u github feature/pagination-sweep-b
gh pr create --repo pjgross/envmgr --base feature/pagination-sweep \
  --title "feat(api): restructure and bound the last six list endpoints" \
  --body "..."
```

Note the base is **`feature/pagination-sweep`**, not `main` — B stacks on A (PR #36) and must merge after it. Say so in the PR body.

---

## Self-Review

**Spec coverage.** All six endpoints have a task: RAID → 1, system dependencies → 2, component dependencies → 3, versions → 4, dependency-alerts → 5, membership → 6, docs → 7, verification → 8. The differential-test requirement is carried into every task's Step 1.

**Known soft spots, stated rather than hidden:**

1. The three names the first draft guessed at have since been read and the plan corrected in place. Two guesses were right (`ReleaseDependencyAlert.dependency_id`, the `MembershipState` literals); one was wrong — `ensure_subsystem` takes `name`, not `slot`, and it returns an *existing* row when the name matches, so two distinct subsystems need two distinct names. `ensure_environment` is the helper that takes `slot`. Every name in this plan is now read from the code.
2. Task 4's `add_columns(...).subquery()` + `aliased` construction is the least certain code in the plan. The step says to verify by running the test and gives a fallback rather than asserting it works.
3. The versions tie-break test asserts an invariant rather than a specific winner, because the behaviour it replaces was genuinely undefined. That is deliberate — asserting a winner would be asserting today's accident.
