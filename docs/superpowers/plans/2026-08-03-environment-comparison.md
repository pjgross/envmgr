# Environment Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compare two environments across presence, mocked-vs-real, deployed version and host shape, so a user can answer "why does it work in SIT but not UAT?" and "is UAT a faithful copy of Production?"

**Architecture:** One `GET /api/v1/environments/compare?left=&right=` endpoint returning an already-computed, symmetric diff. A pure-function core (host-shape normalisation, difference classification) sits under a service that assembles both sides in SQL. The frontend is a standalone URL-driven page; nominating a reference environment is presentation only and never reaches the API.

**Tech Stack:** FastAPI + SQLAlchemy async + PostgreSQL/SQLite (dual-engine tests) · React 18 + TypeScript + MUI · pytest · vitest

**Spec:** [docs/superpowers/specs/2026-08-03-environment-comparison-design.md](../specs/2026-08-03-environment-comparison-design.md)

## Global Constraints

- No new tables and no Alembic migration. Every field already exists.
- `/compare` must be declared **before** `/{env_id}` in `environments.py`, or FastAPI matches `compare` against the int path parameter and returns 422.
- The API is **symmetric**. There is no `reference` query parameter; the reference is applied in the UI.
- `presence != "both"` ⇒ `differences` is exactly `["presence"]`, never presence plus the other kinds.
- A version absent on **both** sides is not a difference. Absent on one side is.
- `mock_notes` is displayed but never compared.
- `host_shape` compares `{component_type, role, count}`, never host identity or name.
- Sort every multi-row result by a unique key; `apply_sort` and paging are not used here, but determinism across engines still is.
- Render entities by name everywhere — environments, systems, subsystems, component types. Never `#id`.
- Backend tests must pass on **both** engines: default SQLite plus `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test`.
- Every test is verified by breaking what it covers, and the mutation output is reported.

## File Structure

**Backend**
- Create `backend/app/services/environment_comparison.py` — pure functions: host-shape normalisation and difference classification. No DB access, so the risky logic is testable without fixtures.
- Create `backend/app/services/environment_comparison_service.py` — loads both sides and assembles the response. Depends on the module above.
- Create `backend/app/api/v1/schemas/environment_comparison.py` — response models.
- Modify `backend/app/api/v1/environments.py` — the `/compare` route.
- Create `backend/tests/services/test_environment_comparison.py` — pure-function tests.
- Create `backend/tests/services/test_environment_comparison_service.py` — service tests with fixtures.
- Create `backend/tests/integration/test_environment_comparison_api.py` — endpoint tests.

**Frontend**
- Create `frontend/src/types/environmentComparison.ts`
- Create `frontend/src/services/environmentComparisonService.ts`
- Create `frontend/src/pages/environments/EnvironmentCompare.tsx` — pickers, URL state, summary strip.
- Create `frontend/src/components/environments/ComparisonTable.tsx` — the grouped side-by-side table. Split from the page so neither file does two jobs.
- Modify `frontend/src/App.tsx` — route.
- Modify `frontend/src/components/navConfig.tsx` — nav entry.
- Create `frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx`

---

### Task 1: Pure comparison functions

The riskiest logic, isolated from the database so it can be tested exhaustively.

**Files:**
- Create: `backend/app/services/environment_comparison.py`
- Test: `backend/tests/services/test_environment_comparison.py`

**Interfaces:**
- Produces: `host_shape(attachments: list[tuple[str, str | None]]) -> list[dict]` and `difference_kinds(presence: str, left: dict | None, right: dict | None) -> list[str]`. Task 2 consumes both.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_environment_comparison.py`:

```python
"""Pure comparison logic — no database.

Host names differ between environments by design (sit-app-01 vs uat-app-01),
so comparing identity would mark every subsystem different. These functions
define what "the hosts differ" actually means.
"""
from app.services.environment_comparison import difference_kinds, host_shape


def test_host_shape_counts_duplicates():
    shape = host_shape([("server", "primary"), ("server", "primary")])
    assert shape == [{"component_type": "server", "role": "primary", "count": 2}]


def test_host_shape_is_order_independent():
    # THE test for this module: two environments list the same hosts in a
    # different order and must compare equal.
    a = host_shape([("server", "primary"), ("cache", None)])
    b = host_shape([("cache", None), ("server", "primary")])
    assert a == b


def test_host_shape_handles_a_null_role():
    # role is nullable on environment_subsystem_host; sorting must not raise.
    assert host_shape([("cache", None)]) == [
        {"component_type": "cache", "role": None, "count": 1}
    ]


def test_host_shape_distinguishes_role():
    primary = host_shape([("server", "primary")])
    standby = host_shape([("server", "standby")])
    assert primary != standby


def test_host_shape_distinguishes_type():
    assert host_shape([("server", None)]) != host_shape([("cache", None)])


def test_host_shape_of_nothing_is_empty():
    assert host_shape([]) == []


def _side(*, mocked=False, version="1.0", shape=None):
    return {"is_mocked": mocked, "version": version, "host_shape": shape or []}


def test_a_subsystem_on_one_side_only_is_exactly_one_difference():
    """Not presence AND version AND mocked AND host_shape.

    The absent side has no version, no mocked flag and no hosts, so comparing
    them would report a missing subsystem as four differences and inflate every
    count in the summary. The natural implementation — compare each dimension,
    then add presence — gets this wrong.
    """
    assert difference_kinds("left_only", _side(), None) == ["presence"]
    assert difference_kinds("right_only", None, _side()) == ["presence"]


def test_identical_sides_have_no_differences():
    assert difference_kinds("both", _side(), _side()) == []


def test_mocked_difference_is_reported():
    assert difference_kinds("both", _side(mocked=True), _side(mocked=False)) == ["mocked"]


def test_version_difference_is_reported():
    assert difference_kinds("both", _side(version="1.0"), _side(version="2.0")) == ["version"]


def test_a_version_missing_on_both_sides_is_not_a_difference():
    assert difference_kinds("both", _side(version=None), _side(version=None)) == []


def test_a_version_missing_on_one_side_is_a_difference():
    assert difference_kinds("both", _side(version=None), _side(version="2.0")) == ["version"]


def test_host_shape_difference_is_reported():
    left = _side(shape=host_shape([("server", "primary")]))
    right = _side(shape=host_shape([("server", "primary"), ("server", "standby")]))
    assert difference_kinds("both", left, right) == ["host_shape"]


def test_several_differences_are_all_reported_in_a_stable_order():
    left = _side(mocked=True, version="1.0")
    right = _side(mocked=False, version="2.0")
    assert difference_kinds("both", left, right) == ["mocked", "version"]
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_comparison.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.environment_comparison'`.

- [ ] **Step 3: Implement**

Create `backend/app/services/environment_comparison.py`:

```python
"""Pure comparison logic for environment diffs — no database access.

Kept separate from the service so the rules that decide what counts as a
difference can be tested exhaustively without fixtures.
"""
from collections import Counter
from typing import Optional

# Order is fixed so `differences` arrays compare equal regardless of how they
# were built, and so the UI can render chips in a stable order.
_KIND_ORDER = ("mocked", "version", "host_shape")


def host_shape(attachments: list[tuple[str, Optional[str]]]) -> list[dict]:
    """Normalise a subsystem's host attachments into a comparable shape.

    `attachments` is (component_type, role) per host. Host *names* differ
    between environments by design, so identity is never compared — what
    matters is how many hosts of what type and role a subsystem runs on.

    Sorted, so equality is a plain structural comparison rather than a set
    intersection. `role` is nullable, hence the `or ""` in the sort key.
    """
    counts = Counter(attachments)
    return sorted(
        (
            {"component_type": component_type, "role": role, "count": count}
            for (component_type, role), count in counts.items()
        ),
        key=lambda entry: (entry["component_type"], entry["role"] or ""),
    )


def difference_kinds(
    presence: str, left: Optional[dict], right: Optional[dict]
) -> list[str]:
    """Which dimensions differ between the two sides.

    A subsystem present on only one side is exactly one difference —
    "presence" — and never also a version/mocked/host difference. The absent
    side has no values to compare, so reporting four differences for one
    missing subsystem would inflate every count in the summary.
    """
    if presence != "both":
        return ["presence"]

    assert left is not None and right is not None
    differing = {
        "mocked": left["is_mocked"] != right["is_mocked"],
        # None == None is not a difference: a subsystem nobody has recorded a
        # version for on either side is consistent, not divergent.
        "version": left["version"] != right["version"],
        "host_shape": left["host_shape"] != right["host_shape"],
    }
    return [kind for kind in _KIND_ORDER if differing[kind]]
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_comparison.py -q
```

Expected: `14 passed`.

- [ ] **Step 5: Verify the tests discriminate**

Run each mutation, confirm the named test fails, restore, and report the output. Back the file up first — do **not** use `git checkout` to restore, it discards uncommitted work in the same file:

```bash
cp app/services/environment_comparison.py /tmp/ec.bak
```

1. Delete `sorted(...)` and return the comprehension as a plain `list`. Expected: `test_host_shape_is_order_independent` FAILS.
2. Change the `presence != "both"` early return to fall through and compare anyway. Expected: `test_a_subsystem_on_one_side_only_is_exactly_one_difference` FAILS.
3. Drop `role` from the `host_shape` dict and its sort key. Expected: `test_host_shape_distinguishes_role` FAILS.

Restore with `cp /tmp/ec.bak app/services/environment_comparison.py` after each.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/environment_comparison.py backend/tests/services/test_environment_comparison.py
git commit -m "feat(environments): pure comparison logic for environment diffs"
```

---

### Task 2: The comparison service

**Files:**
- Create: `backend/app/services/environment_comparison_service.py`
- Test: `backend/tests/services/test_environment_comparison_service.py`

**Interfaces:**
- Consumes: `host_shape`, `difference_kinds` from Task 1. `environment_service.get_environment(db, env_id, tenant_id) -> Environment` (raises 404).
- Produces: `compare_environments(db, left_id, right_id, tenant_id) -> dict` with keys `left`, `right`, `systems`, `subsystems`, `summary`. Task 3 serialises it.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/services/test_environment_comparison_service.py`:

```python
"""Environment comparison assembled from the database, both engines."""
import pytest
from datetime import datetime, timezone
from sqlalchemy import select

from app.db.models.environment import (
    Environment,
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentSystem,
)
from app.db.models.infrastructure_component import (
    InfrastructureComponent,
    InfrastructureComponentType,
)
from app.db.models.system import SubSystem, System
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import environment_comparison_service as svc


@pytest.fixture
async def fixture_pair(db_session, test_tenant):
    """Two environments, one shared system, one shared subsystem."""
    left = Environment(tenant_id=test_tenant.id, name="SIT", environment_type="test")
    right = Environment(tenant_id=test_tenant.id, name="UAT", environment_type="test")
    system = System(tenant_id=test_tenant.id, name="Payments")
    db_session.add_all([left, right, system])
    await db_session.flush()

    sub = SubSystem(tenant_id=test_tenant.id, system_id=system.id, name="api")
    db_session.add(sub)
    await db_session.flush()

    for env in (left, right):
        db_session.add(EnvironmentSystem(
            tenant_id=test_tenant.id, environment_id=env.id, system_id=system.id))
        db_session.add(EnvironmentSubSystem(
            tenant_id=test_tenant.id, environment_id=env.id, subsystem_id=sub.id,
            is_mocked=False))
    await db_session.flush()
    return {"left": left, "right": right, "system": system, "sub": sub}


async def _host(db_session, tenant_id, env, sub_id, *, component_type, role, name):
    component = InfrastructureComponent(
        tenant_id=tenant_id, name=name, component_type=component_type)
    db_session.add(component)
    await db_session.flush()
    env_sub = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env.id,
            EnvironmentSubSystem.subsystem_id == sub_id,
        )
    )).scalar_one()
    db_session.add(EnvironmentSubSystemHost(
        tenant_id=tenant_id, environment_subsystem_id=env_sub.id,
        infrastructure_component_id=component.id, role=role))
    await db_session.flush()


@pytest.mark.asyncio
async def test_identical_environments_report_no_differences(
    db_session, test_tenant, fixture_pair
):
    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    assert result["summary"]["differing"] == 0
    assert all(row["differences"] == [] for row in result["subsystems"])


@pytest.mark.asyncio
async def test_same_host_shape_with_different_hostnames_is_not_a_difference(
    db_session, test_tenant, fixture_pair
):
    """The whole justification for host_shape.

    sit-app-01 and uat-app-01 are the same shape. If this ever fails, someone
    has changed the comparison back to host identity.
    """
    await _host(db_session, test_tenant.id, fixture_pair["left"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="sit-app-01")
    await _host(db_session, test_tenant.id, fixture_pair["right"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="uat-app-01")

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == []


@pytest.mark.asyncio
async def test_a_different_replica_count_is_a_host_shape_difference(
    db_session, test_tenant, fixture_pair
):
    await _host(db_session, test_tenant.id, fixture_pair["left"], fixture_pair["sub"].id,
                component_type=InfrastructureComponentType.SERVER, role="primary",
                name="sit-app-01")
    for name in ("uat-app-01", "uat-app-02"):
        await _host(db_session, test_tenant.id, fixture_pair["right"], fixture_pair["sub"].id,
                    component_type=InfrastructureComponentType.SERVER, role="primary",
                    name=name)

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["host_shape"]
    assert row["left"]["host_shape"][0]["count"] == 1
    assert row["right"]["host_shape"][0]["count"] == 2


@pytest.mark.asyncio
async def test_a_mocked_subsystem_differs_from_a_real_one(
    db_session, test_tenant, fixture_pair
):
    env_sub = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == fixture_pair["right"].id)
    )).scalar_one()
    env_sub.is_mocked = True
    env_sub.mock_notes = "stubbed until the gateway contract lands"
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["mocked"]
    # mock_notes travels for display but is never compared.
    assert row["right"]["mock_notes"] == "stubbed until the gateway contract lands"


@pytest.mark.asyncio
async def test_differing_mock_notes_alone_is_not_a_difference(
    db_session, test_tenant, fixture_pair
):
    """Free text would otherwise make every mocked subsystem differ."""
    rows = (await db_session.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.subsystem_id == fixture_pair["sub"].id)
    )).scalars().all()
    for i, row in enumerate(rows):
        row.is_mocked = True
        row.mock_notes = f"note {i}"
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == []


@pytest.mark.asyncio
async def test_version_differences_and_the_both_absent_case(
    db_session, test_tenant, fixture_pair
):
    # Absent on both sides first — must not be a difference.
    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)
    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["left"]["version"] is None and row["right"]["version"] is None
    assert row["differences"] == []

    # Now record one side only.
    db_session.add(EnvironmentSubSystemVersion(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=fixture_pair["sub"].id, build_identifier="b-1",
        version_label="1.4.0", installed_at=datetime(2026, 6, 1, tzinfo=timezone.utc)))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)
    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["differences"] == ["version"]
    assert row["left"]["version"] == "1.4.0"


@pytest.mark.asyncio
async def test_the_version_used_is_the_current_one_not_the_first(
    db_session, test_tenant, fixture_pair
):
    """Two versions recorded for the same subsystem; the later one wins."""
    for label, day in (("1.0.0", 1), ("2.0.0", 9)):
        db_session.add(EnvironmentSubSystemVersion(
            tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
            subsystem_id=fixture_pair["sub"].id, build_identifier=f"b-{label}",
            version_label=label,
            installed_at=datetime(2026, 6, day, tzinfo=timezone.utc)))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == fixture_pair["sub"].id)
    assert row["left"]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_a_subsystem_on_one_side_only_reports_presence_alone(
    db_session, test_tenant, fixture_pair
):
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="worker")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=True))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    row = next(r for r in result["subsystems"] if r["subsystem_id"] == extra.id)
    assert row["presence"] == "left_only"
    assert row["differences"] == ["presence"]
    assert row["right"] is None


@pytest.mark.asyncio
async def test_the_summary_agrees_with_the_rows(db_session, test_tenant, fixture_pair):
    """These are the two numbers that drifted apart three times in the
    pagination programme. They are built from the same arrays here."""
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="worker")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=False))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    rows = result["subsystems"]
    summary = result["summary"]
    assert summary["compared"] == len(rows)
    assert summary["differing"] == sum(1 for r in rows if r["differences"])
    for kind in ("presence", "mocked", "version", "host_shape"):
        assert summary["by_kind"][kind] == sum(
            1 for r in rows if kind in r["differences"]), kind


@pytest.mark.asyncio
async def test_differing_rows_come_first(db_session, test_tenant, fixture_pair):
    extra = SubSystem(tenant_id=test_tenant.id,
                      system_id=fixture_pair["system"].id, name="aaa-first-alphabetically")
    db_session.add(extra)
    await db_session.flush()
    db_session.add(EnvironmentSubSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["left"].id,
        subsystem_id=extra.id, is_mocked=False))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    assert result["subsystems"][0]["differences"] != []


@pytest.mark.asyncio
async def test_systems_presence_is_reported(db_session, test_tenant, fixture_pair):
    other = System(tenant_id=test_tenant.id, name="Reporting")
    db_session.add(other)
    await db_session.flush()
    db_session.add(EnvironmentSystem(
        tenant_id=test_tenant.id, environment_id=fixture_pair["right"].id,
        system_id=other.id))
    await db_session.flush()

    result = await svc.compare_environments(
        db_session, fixture_pair["left"].id, fixture_pair["right"].id, test_tenant.id)

    by_name = {s["name"]: s for s in result["systems"]}
    assert by_name["Payments"]["presence"] == "both"
    assert by_name["Reporting"]["presence"] == "right_only"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_comparison_service.py -q
```

Expected: collection error — no module `app.services.environment_comparison_service`.

- [ ] **Step 3: Implement**

Create `backend/app/services/environment_comparison_service.py`:

```python
"""Assemble a symmetric diff of two environments.

Everything is loaded per side and compared in Python over small in-memory
maps rather than as one large join: the result is bounded by the two
environments' own subsystems, and the per-dimension rules (see
`environment_comparison`) are far clearer as expressions than as SQL.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.environment import (
    EnvironmentSubSystem,
    EnvironmentSubSystemHost,
    EnvironmentSystem,
)
from app.db.models.infrastructure_component import InfrastructureComponent
from app.db.models.system import SubSystem, System
from app.services.environment_comparison import difference_kinds, host_shape
from app.services.environment_service import get_environment
from app.services.version_service import list_versions

_KINDS = ("presence", "mocked", "version", "host_shape")


async def _systems(db: AsyncSession, env_id: int, tenant_id: int) -> dict[int, str]:
    rows = (await db.execute(
        select(System.id, System.name)
        .join(EnvironmentSystem, EnvironmentSystem.system_id == System.id)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )).all()
    return {sid: name for sid, name in rows}


async def _side(db: AsyncSession, env_id: int, tenant_id: int) -> dict[int, dict]:
    """Everything comparable about one environment, keyed by subsystem id."""
    rows = (await db.execute(
        select(
            EnvironmentSubSystem.id,
            SubSystem.id,
            SubSystem.name,
            System.id,
            System.name,
            EnvironmentSubSystem.is_mocked,
            EnvironmentSubSystem.mock_notes,
        )
        .join(SubSystem, SubSystem.id == EnvironmentSubSystem.subsystem_id)
        .join(System, System.id == SubSystem.system_id)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )).all()

    env_sub_ids = [r[0] for r in rows]
    hosts: dict[int, list[tuple[str, Optional[str]]]] = {i: [] for i in env_sub_ids}
    if env_sub_ids:
        host_rows = (await db.execute(
            select(
                EnvironmentSubSystemHost.environment_subsystem_id,
                InfrastructureComponent.component_type,
                EnvironmentSubSystemHost.role,
            )
            .join(
                InfrastructureComponent,
                InfrastructureComponent.id
                == EnvironmentSubSystemHost.infrastructure_component_id,
            )
            .where(
                EnvironmentSubSystemHost.environment_subsystem_id.in_(env_sub_ids),
                EnvironmentSubSystemHost.tenant_id == tenant_id,
                EnvironmentSubSystemHost.deleted_at.is_(None),
            )
        )).all()
        for env_sub_id, component_type, role in host_rows:
            value = getattr(component_type, "value", component_type)
            hosts[env_sub_id].append((value, role))

    # Reuse the endpoint's own current-version semantics rather than
    # reimplementing the dedup: list_versions already resolves "latest per
    # subsystem" with a ROW_NUMBER() window under current_only.
    version_rows, _total = await list_versions(db, env_id, tenant_id, current_only=True)
    versions = {v.subsystem_id: v.version_label for v in version_rows}

    return {
        sub_id: {
            "subsystem_id": sub_id,
            "name": sub_name,
            "system_id": system_id,
            "system_name": system_name,
            "is_mocked": is_mocked,
            "mock_notes": mock_notes,
            "version": versions.get(sub_id),
            "host_shape": host_shape(hosts[env_sub_id]),
        }
        for (env_sub_id, sub_id, sub_name, system_id, system_name,
             is_mocked, mock_notes) in rows
    }


def _presence(in_left: bool, in_right: bool) -> str:
    if in_left and in_right:
        return "both"
    return "left_only" if in_left else "right_only"


async def compare_environments(
    db: AsyncSession, left_id: int, right_id: int, tenant_id: int
) -> dict:
    left_env = await get_environment(db, left_id, tenant_id)
    right_env = await get_environment(db, right_id, tenant_id)

    left_systems = await _systems(db, left_id, tenant_id)
    right_systems = await _systems(db, right_id, tenant_id)
    systems = [
        {
            "system_id": sid,
            "name": left_systems.get(sid) or right_systems[sid],
            "presence": _presence(sid in left_systems, sid in right_systems),
        }
        for sid in sorted(set(left_systems) | set(right_systems))
    ]
    systems.sort(key=lambda s: (s["name"].lower(), s["system_id"]))

    left_side = await _side(db, left_id, tenant_id)
    right_side = await _side(db, right_id, tenant_id)

    subsystems = []
    for sub_id in set(left_side) | set(right_side):
        left = left_side.get(sub_id)
        right = right_side.get(sub_id)
        meta = left or right
        presence = _presence(left is not None, right is not None)
        subsystems.append({
            "subsystem_id": sub_id,
            "name": meta["name"],
            "system_id": meta["system_id"],
            "system_name": meta["system_name"],
            "presence": presence,
            "left": _payload(left),
            "right": _payload(right),
            "differences": difference_kinds(presence, left, right),
        })

    # Differing first, then by system and subsystem name, with the id as a
    # unique tiebreaker so the order is identical on both engines.
    subsystems.sort(
        key=lambda r: (
            not r["differences"],
            r["system_name"].lower(),
            r["name"].lower(),
            r["subsystem_id"],
        )
    )

    return {
        "left": {"id": left_env.id, "name": left_env.name, "status": left_env.status},
        "right": {"id": right_env.id, "name": right_env.name, "status": right_env.status},
        "systems": systems,
        "subsystems": subsystems,
        "summary": {
            "compared": len(subsystems),
            "differing": sum(1 for r in subsystems if r["differences"]),
            # Built from the same arrays the rows carry, so a row and the
            # summary cannot disagree.
            "by_kind": {
                kind: sum(1 for r in subsystems if kind in r["differences"])
                for kind in _KINDS
            },
        },
    }


def _payload(side: Optional[dict]) -> Optional[dict]:
    if side is None:
        return None
    return {
        "is_mocked": side["is_mocked"],
        "mock_notes": side["mock_notes"],
        "version": side["version"],
        "host_shape": side["host_shape"],
    }
```

- [ ] **Step 4: Run to verify they pass, on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/services/test_environment_comparison_service.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/services/test_environment_comparison_service.py -q
```

Expected: `11 passed` on each.

- [ ] **Step 5: Verify the tests discriminate**

`cp app/services/environment_comparison_service.py /tmp/ecs.bak` first; restore with `cp` after each, never `git checkout`.

1. Change `list_versions(..., current_only=True)` to `current_only=False`. Expected: `test_the_version_used_is_the_current_one_not_the_first` FAILS.
2. Compute `by_kind` from a separate pass that re-derives differences instead of reading `r["differences"]` — e.g. count `presence != "both"` for the presence kind and compare all three other dimensions unconditionally. Expected: `test_the_summary_agrees_with_the_rows` FAILS.
3. Remove `not r["differences"]` from the sort key. Expected: `test_differing_rows_come_first` FAILS.
4. Include `InfrastructureComponent.name` in the host tuple. Expected: `test_same_host_shape_with_different_hostnames_is_not_a_difference` FAILS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/environment_comparison_service.py \
        backend/tests/services/test_environment_comparison_service.py
git commit -m "feat(environments): assemble a symmetric two-environment diff"
```

---

### Task 3: The endpoint

**Files:**
- Create: `backend/app/api/v1/schemas/environment_comparison.py`
- Modify: `backend/app/api/v1/environments.py` (insert the route immediately before `@router.get("/{env_id}")`, currently at line 83)
- Test: `backend/tests/integration/test_environment_comparison_api.py`

**Interfaces:**
- Consumes: `compare_environments(db, left_id, right_id, tenant_id) -> dict` from Task 2.
- Produces: `GET /api/v1/environments/compare?left=&right=` returning `EnvironmentComparisonResponse`. Task 4's frontend service calls it.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/integration/test_environment_comparison_api.py`:

```python
"""GET /api/v1/environments/compare."""
import pytest
from httpx import AsyncClient

from app.db.models.environment import Environment


@pytest.fixture
async def two_envs(db_session, test_tenant):
    a = Environment(tenant_id=test_tenant.id, name="SIT", environment_type="test")
    b = Environment(tenant_id=test_tenant.id, name="UAT", environment_type="test")
    db_session.add_all([a, b])
    await db_session.commit()
    await db_session.refresh(a)
    await db_session.refresh(b)
    return a, b


@pytest.mark.asyncio
async def test_compare_is_not_swallowed_by_the_env_id_route(
    client: AsyncClient, auth_headers, two_envs
):
    """`/environments/compare` must be declared before `/environments/{env_id}`.

    Declared after, FastAPI matches "compare" against the int path parameter
    and answers 422 — the request never reaches this endpoint at all.
    """
    left, right = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": right.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["left"]["name"] == "SIT"
    assert body["right"]["name"] == "UAT"
    assert body["summary"]["compared"] == 0


@pytest.mark.asyncio
async def test_comparing_an_environment_with_itself_is_422(
    client: AsyncClient, auth_headers, two_envs
):
    left, _ = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": left.id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_environment_is_404(client: AsyncClient, auth_headers, two_envs):
    left, _ = two_envs
    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": 9_999_999},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_another_tenants_environment_is_404(
    client: AsyncClient, auth_headers, db_session, two_envs, second_tenant_factory
):
    """Not 403 — the caller must not learn the environment exists."""
    left, _ = two_envs
    other_tenant = await second_tenant_factory()
    foreign = Environment(
        tenant_id=other_tenant.id, name="Their UAT", environment_type="test")
    db_session.add(foreign)
    await db_session.commit()
    await db_session.refresh(foreign)

    resp = await client.get(
        "/api/v1/environments/compare",
        headers=auth_headers,
        params={"left": left.id, "right": foreign.id},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_is_401(client: AsyncClient, two_envs):
    left, right = two_envs
    resp = await client.get(
        "/api/v1/environments/compare", params={"left": left.id, "right": right.id})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_environment_comparison_api.py -q
```

Expected: the first test FAILS with 422 (the `{env_id}` route matching "compare"), the rest fail on status codes.

- [ ] **Step 3: Implement the schemas**

Create `backend/app/api/v1/schemas/environment_comparison.py`:

```python
from typing import Literal, Optional

from pydantic import BaseModel

Presence = Literal["both", "left_only", "right_only"]
DifferenceKind = Literal["presence", "mocked", "version", "host_shape"]


class ComparedEnvironment(BaseModel):
    id: int
    name: str
    status: str


class HostShapeEntry(BaseModel):
    """How many hosts of a given type and role, never which hosts.

    Host names differ between environments by design, so identity is not
    compared — see docs/superpowers/specs/2026-08-03-environment-comparison-design.md.
    """
    component_type: str
    role: Optional[str] = None
    count: int


class SystemPresence(BaseModel):
    system_id: int
    name: str
    presence: Presence


class SubsystemSide(BaseModel):
    is_mocked: bool
    # Displayed, never compared: free text would make every mocked subsystem differ.
    mock_notes: Optional[str] = None
    version: Optional[str] = None
    host_shape: list[HostShapeEntry]


class SubsystemComparison(BaseModel):
    subsystem_id: int
    name: str
    system_id: int
    system_name: str
    presence: Presence
    left: Optional[SubsystemSide] = None
    right: Optional[SubsystemSide] = None
    differences: list[DifferenceKind]


class ComparisonSummary(BaseModel):
    compared: int
    differing: int
    by_kind: dict[str, int]


class EnvironmentComparisonResponse(BaseModel):
    left: ComparedEnvironment
    right: ComparedEnvironment
    systems: list[SystemPresence]
    subsystems: list[SubsystemComparison]
    summary: ComparisonSummary
```

- [ ] **Step 4: Implement the route**

In `backend/app/api/v1/environments.py`, add the imports near the other schema imports:

```python
from app.api.v1.schemas.environment_comparison import EnvironmentComparisonResponse
from app.services import environment_comparison_service
```

`HTTPException` is **not** currently imported in this file — line 4 reads
`from fastapi import APIRouter, Depends, Response, Query, status`. Add it:

```python
from fastapi import APIRouter, Depends, HTTPException, Response, Query, status
```

Then insert this **immediately before** `@router.get("/{env_id}", ...)`:

```python
# MUST stay above `/{env_id}`: declared after it, FastAPI matches "compare"
# against the int path parameter and answers 422 without ever reaching here.
@router.get("/compare", response_model=EnvironmentComparisonResponse)
async def compare_environments_endpoint(
    left: int = Query(..., description="Left-hand environment id"),
    right: int = Query(..., description="Right-hand environment id"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Symmetric diff of two environments.

    There is no `reference` parameter by design: nominating a reference
    environment reframes the same differences as risk, which is presentation.
    Keeping it out of the API means one response serves both the triage and
    fidelity views.
    """
    if left == right:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "left and right must be different environments",
        )
    return await environment_comparison_service.compare_environments(
        db, left, right, current_user.active_tenant_id
    )
```

- [ ] **Step 5: Run to verify they pass, on both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest tests/integration/test_environment_comparison_api.py -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest tests/integration/test_environment_comparison_api.py -q
```

Expected: `5 passed` on each.

- [ ] **Step 6: Verify the tests discriminate**

`cp app/api/v1/environments.py /tmp/envapi.bak` first.

1. Move the `/compare` route to below `@router.get("/{env_id}")`. Expected: `test_compare_is_not_swallowed_by_the_env_id_route` FAILS with 422. **This is the mutation that matters** — it reproduces the ordering bug the route comment warns about.
2. Delete the `left == right` check. Expected: `test_comparing_an_environment_with_itself_is_422` FAILS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/environment_comparison.py \
        backend/app/api/v1/environments.py \
        backend/tests/integration/test_environment_comparison_api.py
git commit -m "feat(environments): GET /environments/compare"
```

---

### Task 4: Frontend types, service, and the page shell

Pickers and URL state, with the table stubbed. Ends with something you can open.

**Files:**
- Create: `frontend/src/types/environmentComparison.ts`
- Create: `frontend/src/services/environmentComparisonService.ts`
- Create: `frontend/src/pages/environments/EnvironmentCompare.tsx`
- Modify: `frontend/src/App.tsx` (lazy import beside line 31, route beside line 154)
- Modify: `frontend/src/components/navConfig.tsx` (Environment Definition group, after the Environments entry at line 61)
- Test: `frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx`

**Interfaces:**
- Consumes: `GET /environments/compare` from Task 3; `useAllEnvironments()` from `frontend/src/hooks/useAllEnvironments.ts`, which returns `{ environments, loading, truncated }`.
- Produces: `EnvironmentComparison` type and `environmentComparisonService.compare(left, right)`. Task 5 renders `comparison.subsystems`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/environmentComparisonService', () => ({
  environmentComparisonService: { compare: vi.fn() },
}));

vi.mock('../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: vi.fn(() => ({
    environments: [
      { id: 2, name: 'SIT' },
      { id: 3, name: 'UAT' },
    ],
    loading: false,
    truncated: false,
  })),
}));

import { environmentComparisonService } from '../../../services/environmentComparisonService';
import { useAllEnvironments } from '../../../hooks/useAllEnvironments';
import EnvironmentCompare from '../EnvironmentCompare';

const EMPTY = {
  left: { id: 2, name: 'SIT', status: 'active' },
  right: { id: 3, name: 'UAT', status: 'active' },
  systems: [],
  subsystems: [],
  summary: { compared: 0, differing: 0, by_kind: { presence: 0, mocked: 0, version: 0, host_shape: 0 } },
};

function renderPage(url = '/environments/compare?left=2&right=3') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <EnvironmentCompare />
    </MemoryRouter>
  );
}

describe('EnvironmentCompare', () => {
  it('reads both environments from the URL and fetches that pair', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    await waitFor(() =>
      expect(environmentComparisonService.compare).toHaveBeenCalledWith(2, 3)
    );
  });

  it('does not fetch until both sides are chosen', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage('/environments/compare?left=2');
    // Give any effect a chance to run before asserting the negative.
    await new Promise((r) => setTimeout(r, 50));
    expect(environmentComparisonService.compare).not.toHaveBeenCalled();
  });

  it('says the environments match rather than showing an empty table', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    expect(await screen.findByText(/match on all four dimensions/i)).toBeInTheDocument();
  });

  it('swap exchanges the two sides', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    await waitFor(() => expect(environmentComparisonService.compare).toHaveBeenCalled());
    vi.mocked(environmentComparisonService.compare).mockClear();

    await userEvent.click(screen.getByRole('button', { name: /swap/i }));

    await waitFor(() =>
      expect(environmentComparisonService.compare).toHaveBeenCalledWith(3, 2)
    );
  });

  it('surfaces a truncated environment list, because a picker missing options is silent', async () => {
    vi.mocked(useAllEnvironments).mockReturnValueOnce({
      environments: [{ id: 2, name: 'SIT' }],
      loading: false,
      truncated: true,
    } as ReturnType<typeof useAllEnvironments>);
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);

    renderPage('/environments/compare');

    expect(await screen.findByText(/only the first/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/pages/environments/__tests__/EnvironmentCompare.test.tsx
```

Expected: FAIL — `EnvironmentCompare` cannot be resolved.

- [ ] **Step 3: Implement the types**

Create `frontend/src/types/environmentComparison.ts`:

```ts
export type Presence = 'both' | 'left_only' | 'right_only';
export type DifferenceKind = 'presence' | 'mocked' | 'version' | 'host_shape';

export interface HostShapeEntry {
  component_type: string;
  role: string | null;
  count: number;
}

export interface ComparedEnvironment {
  id: number;
  name: string;
  status: string;
}

export interface SystemPresence {
  system_id: number;
  name: string;
  presence: Presence;
}

export interface SubsystemSide {
  is_mocked: boolean;
  /** Displayed, never compared. */
  mock_notes: string | null;
  version: string | null;
  host_shape: HostShapeEntry[];
}

export interface SubsystemComparison {
  subsystem_id: number;
  name: string;
  system_id: number;
  system_name: string;
  presence: Presence;
  left: SubsystemSide | null;
  right: SubsystemSide | null;
  differences: DifferenceKind[];
}

export interface EnvironmentComparison {
  left: ComparedEnvironment;
  right: ComparedEnvironment;
  systems: SystemPresence[];
  subsystems: SubsystemComparison[];
  summary: {
    compared: number;
    differing: number;
    by_kind: Record<DifferenceKind, number>;
  };
}
```

- [ ] **Step 4: Implement the service**

Create `frontend/src/services/environmentComparisonService.ts`:

```ts
import api from './api';
import type { EnvironmentComparison } from '../types/environmentComparison';

export const environmentComparisonService = {
  /**
   * The response is symmetric — there is no `reference` parameter. Nominating
   * a reference environment is presentation, applied in the page.
   */
  compare: (left: number, right: number): Promise<EnvironmentComparison> =>
    api.get('/environments/compare', { params: { left, right } }).then((r) => r.data),
};
```

- [ ] **Step 5: Implement the page shell**

Create `frontend/src/pages/environments/EnvironmentCompare.tsx`:

```tsx
/**
 * Compare two environments across presence, mocked-vs-real, deployed version
 * and host shape.
 *
 * The URL carries the whole view, so a comparison is shareable and survives a
 * refresh. `reference` is presentation only: the API returns the same
 * symmetric diff either way, and this page relabels the result.
 */
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography,
} from '@mui/material';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { environmentComparisonService } from '../../services/environmentComparisonService';
import type { EnvironmentComparison } from '../../types/environmentComparison';

export default function EnvironmentCompare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { environments, truncated } = useAllEnvironments();

  const left = searchParams.get('left');
  const right = searchParams.get('right');

  const [comparison, setComparison] = useState<EnvironmentComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!left || !right) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError(null);
    environmentComparisonService
      .compare(Number(left), Number(right))
      .then((result) => {
        setComparison(result);
        setError(null);
      })
      .catch((err: unknown) => {
        setComparison(null);
        setError(err instanceof Error ? err.message : 'Failed to compare environments');
      })
      .finally(() => setLoading(false));
  }, [left, right]);

  const setSide = useCallback(
    (side: 'left' | 'right', value: string) => {
      const next = new URLSearchParams(searchParams);
      if (value) next.set(side, value);
      else next.delete(side);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const swap = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    if (left) next.set('right', left);
    else next.delete('right');
    if (right) next.set('left', right);
    else next.delete('left');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, left, right]);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Compare Environments</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Differences in what each environment contains, what is mocked, which versions are
        deployed, and how each subsystem is hosted.
      </Typography>

      <Paper sx={{ p: 2, mb: 2, display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <TextField
          select size="small" label="Left" value={left ?? ''} sx={{ minWidth: 200 }}
          onChange={(e) => setSide('left', e.target.value)}
          helperText={
            truncated
              ? `Only the first ${environments.length} environments are listed.`
              : undefined
          }
        >
          {environments.map((env) => (
            <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
          ))}
        </TextField>

        <Button onClick={swap} startIcon={<SwapHorizIcon />} sx={{ mt: 0.5 }}>Swap</Button>

        <TextField
          select size="small" label="Right" value={right ?? ''} sx={{ minWidth: 200 }}
          onChange={(e) => setSide('right', e.target.value)}
        >
          {environments.map((env) => (
            <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
          ))}
        </TextField>
      </Paper>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {!left || !right ? (
        <Typography variant="body2" color="text.secondary">
          Choose two environments to compare.
        </Typography>
      ) : loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
      ) : comparison && comparison.summary.differing === 0 ? (
        <Alert severity="success">
          {comparison.left.name} and {comparison.right.name} match on all four dimensions.
        </Alert>
      ) : null}
    </Box>
  );
}
```

- [ ] **Step 6: Wire the route and nav**

In `frontend/src/App.tsx`, beside the other environment lazy imports (line 31):

```tsx
const EnvironmentCompare = lazy(() => import('./pages/environments/EnvironmentCompare'));
```

And **before** the `/environments/:id` route (line 154), so `compare` is not captured as an id:

```tsx
<Route path="/environments/compare" element={<EnvironmentCompare />} />
```

In `frontend/src/components/navConfig.tsx`, after the Environments entry (line 61):

```tsx
{ label: 'Compare Environments', path: '/environments/compare', icon: <CompareArrowsIcon /> },
```

with `import CompareArrowsIcon from '@mui/icons-material/CompareArrows';` beside the other icon imports.

- [ ] **Step 7: Run to verify they pass**

```bash
cd frontend && npx vitest run src/pages/environments/__tests__/EnvironmentCompare.test.tsx && npx tsc --noEmit
```

Expected: `5 passed`, tsc clean.

Also run the nav test, which asserts the nav shape:

```bash
npx vitest run src/components/__tests__/navConfig.test.tsx
```

If it asserts an exact item count or list, update it to include the new entry.

- [ ] **Step 8: Verify the tests discriminate**

`cp src/pages/environments/EnvironmentCompare.tsx /tmp/ecpage.bak` first.

1. Fetch even when one side is missing (drop the `if (!left || !right)` guard). Expected: `does not fetch until both sides are chosen` FAILS.
2. Make `swap` a no-op. Expected: `swap exchanges the two sides` FAILS.
3. Drop the `truncated` helper text. Expected: the truncation test FAILS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/environmentComparison.ts \
        frontend/src/services/environmentComparisonService.ts \
        frontend/src/pages/environments/EnvironmentCompare.tsx \
        frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx \
        frontend/src/App.tsx frontend/src/components/navConfig.tsx
git commit -m "feat(environments): comparison page shell with URL-driven pickers"
```

---

### Task 5: The comparison table, summary strip and reference framing

**Files:**
- Create: `frontend/src/components/environments/ComparisonTable.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentCompare.tsx` (render the table, summary strip, reference selector, differences-only toggle)
- Test: `frontend/src/components/environments/__tests__/ComparisonTable.test.tsx`
- Test: `frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx` (extend)

**Interfaces:**
- Consumes: `EnvironmentComparison`, `SubsystemComparison`, `HostShapeEntry` from Task 4.
- Produces: `<ComparisonTable rows={SubsystemComparison[]} leftName={string} rightName={string} reference={'left'|'right'|null} />` and the exported helper `formatHostShape(shape: HostShapeEntry[]): string`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/environments/__tests__/ComparisonTable.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ComparisonTable, { formatHostShape } from '../ComparisonTable';
import type { SubsystemComparison } from '../../../types/environmentComparison';

const bothSides = (over: Partial<SubsystemComparison> = {}): SubsystemComparison => ({
  subsystem_id: 1,
  name: 'api',
  system_id: 10,
  system_name: 'Payments',
  presence: 'both',
  left: { is_mocked: false, mock_notes: null, version: '1.0', host_shape: [] },
  right: { is_mocked: false, mock_notes: null, version: '2.0', host_shape: [] },
  differences: ['version'],
  ...over,
});

describe('formatHostShape', () => {
  it('renders count, type and role rather than host names', () => {
    expect(
      formatHostShape([{ component_type: 'server', role: 'primary', count: 2 }])
    ).toBe('2 × server (primary)');
  });

  it('omits the role when there is none', () => {
    expect(formatHostShape([{ component_type: 'cache', role: null, count: 1 }])).toBe(
      '1 × cache'
    );
  });

  it('says none rather than rendering an empty string', () => {
    expect(formatHostShape([])).toBe('—');
  });
});

describe('ComparisonTable', () => {
  it('groups rows under their system name', () => {
    render(<ComparisonTable rows={[bothSides()]} leftName="SIT" rightName="UAT" reference={null} />);
    expect(screen.getByText('Payments')).toBeInTheDocument();
    expect(screen.getByText('api')).toBeInTheDocument();
  });

  it('names the environment a subsystem is missing from, never an id', () => {
    render(
      <ComparisonTable
        rows={[bothSides({ presence: 'left_only', right: null, differences: ['presence'] })]}
        leftName="SIT" rightName="UAT" reference={null}
      />
    );
    expect(screen.getByText(/not in UAT/i)).toBeInTheDocument();
  });

  it('reframes a gap as risk when a reference is nominated', () => {
    // Same data, different label — proving the reference is presentation.
    render(
      <ComparisonTable
        rows={[bothSides({ presence: 'right_only', left: null, differences: ['presence'] })]}
        leftName="SIT" rightName="UAT" reference="left"
      />
    );
    expect(screen.getByText(/extra vs reference/i)).toBeInTheDocument();
  });

  it('shows mock notes without treating them as a difference', () => {
    render(
      <ComparisonTable
        rows={[bothSides({
          left: { is_mocked: true, mock_notes: 'stubbed', version: '1.0', host_shape: [] },
          right: { is_mocked: true, mock_notes: 'also stubbed', version: '1.0', host_shape: [] },
          differences: [],
        })]}
        leftName="SIT" rightName="UAT" reference={null}
      />
    );
    expect(screen.getByText(/stubbed/)).toBeInTheDocument();
  });
});
```

Add to `frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx`:

```tsx
  it('filters to differing rows and agrees with the summary count', async () => {
    // The filter and the summary must come from the same place — these are the
    // two numbers that drifted apart repeatedly in the pagination programme.
    vi.mocked(environmentComparisonService.compare).mockResolvedValue({
      ...EMPTY,
      subsystems: [
        {
          subsystem_id: 1, name: 'api', system_id: 10, system_name: 'Payments',
          presence: 'both',
          left: { is_mocked: false, mock_notes: null, version: '1.0', host_shape: [] },
          right: { is_mocked: false, mock_notes: null, version: '2.0', host_shape: [] },
          differences: ['version'],
        },
        {
          subsystem_id: 2, name: 'worker', system_id: 10, system_name: 'Payments',
          presence: 'both',
          left: { is_mocked: false, mock_notes: null, version: '1.0', host_shape: [] },
          right: { is_mocked: false, mock_notes: null, version: '1.0', host_shape: [] },
          differences: [],
        },
      ],
      summary: { compared: 2, differing: 1, by_kind: { presence: 0, mocked: 0, version: 1, host_shape: 0 } },
    });

    renderPage();
    expect(await screen.findByText('worker')).toBeInTheDocument();

    await userEvent.click(screen.getByRole('checkbox', { name: /differences only/i }));

    expect(screen.queryByText('worker')).not.toBeInTheDocument();
    expect(screen.getByText('api')).toBeInTheDocument();
    // One row shown, and the summary said one differing.
    expect(screen.getByText(/1 of 2 subsystems differ/i)).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd frontend && npx vitest run src/components/environments/__tests__/ComparisonTable.test.tsx
```

Expected: FAIL — `ComparisonTable` cannot be resolved.

- [ ] **Step 3: Implement the table**

Create `frontend/src/components/environments/ComparisonTable.tsx`:

```tsx
/**
 * Side-by-side subsystem comparison, grouped by system.
 *
 * A plain Table rather than DataGrid: two-sided cells under group headers is
 * not something DataGrid expresses well, and a raw DataGrid would also need
 * `disableColumnFilter` to avoid offering a column filter that contradicts the
 * page's own summary.
 */
import { Fragment } from 'react';
import {
  Chip, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography,
} from '@mui/material';
import type {
  DifferenceKind, HostShapeEntry, SubsystemComparison,
} from '../../types/environmentComparison';

// Exported: the page's summary strip labels the same kinds, and two copies
// would drift.
export const KIND_LABEL: Record<DifferenceKind, string> = {
  presence: 'Presence',
  mocked: 'Mocked',
  version: 'Version',
  host_shape: 'Hosts',
};

/** Count, type and role — never host names, which differ between environments by design. */
export function formatHostShape(shape: HostShapeEntry[]): string {
  if (shape.length === 0) return '—';
  return shape
    .map((e) => `${e.count} × ${e.component_type}${e.role ? ` (${e.role})` : ''}`)
    .join(', ');
}

interface Props {
  rows: SubsystemComparison[];
  leftName: string;
  rightName: string;
  reference: 'left' | 'right' | null;
}

function missingLabel(
  row: SubsystemComparison, leftName: string, rightName: string,
  reference: 'left' | 'right' | null
): string {
  const absentFrom = row.presence === 'left_only' ? rightName : leftName;
  if (reference === null) return `Not in ${absentFrom}`;
  const presentSide = row.presence === 'left_only' ? 'left' : 'right';
  return presentSide === reference ? 'Missing from reference' : 'Extra vs reference';
}

function Side({ side }: { side: SubsystemComparison['left'] }) {
  if (side === null) return <Typography variant="body2" color="text.secondary">—</Typography>;
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2">{side.version ?? 'No version recorded'}</Typography>
      <Typography variant="caption" color="text.secondary">
        {side.is_mocked ? 'Mocked' : 'Real'}
        {side.mock_notes ? ` — ${side.mock_notes}` : ''}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {formatHostShape(side.host_shape)}
      </Typography>
    </Stack>
  );
}

export default function ComparisonTable({ rows, leftName, rightName, reference }: Props) {
  const bySystem = new Map<string, SubsystemComparison[]>();
  rows.forEach((row) => {
    const list = bySystem.get(row.system_name) ?? [];
    list.push(row);
    bySystem.set(row.system_name, list);
  });

  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Subsystem</TableCell>
          <TableCell>{leftName}</TableCell>
          <TableCell>{rightName}</TableCell>
          <TableCell>Differences</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {[...bySystem.entries()].map(([systemName, systemRows]) => (
          // A keyed Fragment, not `<>`: the shorthand cannot take a key, and
          // React warns on every group without one.
          <Fragment key={systemName}>
            <TableRow>
              <TableCell colSpan={4} sx={{ bgcolor: 'action.hover' }}>
                <Typography variant="subtitle2">{systemName}</Typography>
              </TableCell>
            </TableRow>
            {systemRows.map((row) => (
              <TableRow key={row.subsystem_id}>
                <TableCell>{row.name}</TableCell>
                <TableCell><Side side={row.left} /></TableCell>
                <TableCell><Side side={row.right} /></TableCell>
                <TableCell>
                  <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
                    {row.presence !== 'both' && (
                      <Chip size="small" color="warning"
                            label={missingLabel(row, leftName, rightName, reference)} />
                    )}
                    {row.differences
                      .filter((kind) => kind !== 'presence')
                      .map((kind) => (
                        <Chip key={kind} size="small" label={KIND_LABEL[kind]} />
                      ))}
                    {row.differences.length === 0 && (
                      <Typography variant="caption" color="text.secondary">Match</Typography>
                    )}
                  </Stack>
                </TableCell>
              </TableRow>
            ))}
          </Fragment>
        ))}
      </TableBody>
    </Table>
  );
}
```

- [ ] **Step 4: Wire it into the page**

In `EnvironmentCompare.tsx`, add state and render. Add these imports:

```tsx
import { Checkbox, Chip, FormControlLabel, Stack } from '@mui/material';
```

(`Paper`, `Alert`, `MenuItem`, `TextField` and `Typography` are already imported by the page
from Step 5 of Task 4. Merge these names into that existing import rather than adding a
second `@mui/material` import line.)

```tsx
```

Add state beside the others:

```tsx
  const diffOnly = searchParams.get('diff_only') === '1';
  const reference = (searchParams.get('reference') as 'left' | 'right' | null) ?? null;

  const setFlag = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(searchParams);
      if (value === null) next.delete(key);
      else next.set(key, value);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );
```

Add the reference selector and toggle into the controls `Paper`:

```tsx
        <TextField
          select size="small" label="Reference" value={reference ?? ''} sx={{ minWidth: 160 }}
          onChange={(e) => setFlag('reference', e.target.value || null)}
          helperText="Frames gaps as risk against one side"
        >
          <MenuItem value="">None</MenuItem>
          <MenuItem value="left">Left</MenuItem>
          <MenuItem value="right">Right</MenuItem>
        </TextField>
        <FormControlLabel
          control={
            <Checkbox
              checked={diffOnly}
              onChange={(e) => setFlag('diff_only', e.target.checked ? '1' : null)}
            />
          }
          label="Differences only"
        />
```

And replace the trailing `) : null}` block with the results:

```tsx
      ) : comparison ? (
        <>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1">
              {comparison.summary.differing} of {comparison.summary.compared} subsystems differ
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
              {(['presence', 'mocked', 'version', 'host_shape'] as const).map((kind) => (
                <Chip key={kind} size="small"
                      label={`${KIND_LABEL[kind]}: ${comparison.summary.by_kind[kind]}`} />
              ))}
            </Stack>
          </Paper>
          {comparison.summary.differing === 0 ? (
            <Alert severity="success">
              {comparison.left.name} and {comparison.right.name} match on all four dimensions.
            </Alert>
          ) : (
            <Paper>
              <ComparisonTable
                rows={diffOnly
                  ? comparison.subsystems.filter((r) => r.differences.length > 0)
                  : comparison.subsystems}
                leftName={comparison.left.name}
                rightName={comparison.right.name}
                reference={reference}
              />
            </Paper>
          )}
        </>
      ) : null}
```

Add `Chip` and `Stack` to the page's MUI import. `KIND_LABEL` is already exported from
`ComparisonTable.tsx` (Step 3), so import it alongside the component rather than defining a
second copy:

```tsx
import ComparisonTable, { KIND_LABEL } from '../../components/environments/ComparisonTable';
```

- [ ] **Step 5: Run to verify they pass**

```bash
cd frontend && npx vitest run src/components/environments src/pages/environments && npx tsc --noEmit && npm run lint
```

Expected: all pass, tsc clean, lint clean.

- [ ] **Step 6: Verify the tests discriminate**

Back each file up with `cp` first.

1. In `formatHostShape`, return the component types only (drop count and role). Expected: `renders count, type and role rather than host names` FAILS.
2. Make `missingLabel` always return `Not in ${absentFrom}` regardless of `reference`. Expected: `reframes a gap as risk when a reference is nominated` FAILS.
3. In the page, ignore `diffOnly` and always pass the full row list. Expected: `filters to differing rows and agrees with the summary count` FAILS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/environments/ComparisonTable.tsx \
        frontend/src/components/environments/__tests__/ComparisonTable.test.tsx \
        frontend/src/pages/environments/EnvironmentCompare.tsx \
        frontend/src/pages/environments/__tests__/EnvironmentCompare.test.tsx
git commit -m "feat(environments): comparison table, summary and reference framing"
```

---

### Task 6: Correct the Phase 6 docs, verify in a browser, open the PR

**Files:**
- Modify: `docs/phases/phase-6.md`
- Modify: `docs/plan.md` (the Phase 6 row, line 19)
- Modify: `CLAUDE.md` (header)

- [ ] **Step 1: Every gate, both engines**

```bash
cd backend && PYTHONPATH=. uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  PYTHONPATH=. uv run pytest -q
cd ../frontend && npx vitest run && npm run lint && npx tsc --noEmit
```

- [ ] **Step 2: Verify in the browser**

Backend on :8000, `npm run dev` on :5173, signed in as `admin`/`admin123` (tenant `demo`).

Go to **Environment Definition → Compare Environments**, choose two of `EnvMgr_SIT`, `Mortgage SIT`, `Mortgage_UAT`:

- Both pickers list every environment; the page fetches only once both are chosen.
- The summary strip's "N of M subsystems differ" matches the rows shown.
- **Differences only** hides matching rows and the count still reads the same M.
- **Swap** exchanges the columns and the URL follows.
- Nominating a reference relabels a missing subsystem without a new request (watch the Network tab — there should be none).
- A refresh reproduces the view exactly.
- Every environment, system and subsystem renders by name. No `#id` anywhere.

The dev tenant is small. If two environments have no subsystems in common, say so rather than reporting a check you could not really make — and consider attaching a subsystem to a second environment to exercise the diff, reverting it afterwards.

- [ ] **Step 3: Correct `docs/phases/phase-6.md`**

The task list is two-thirds wrong and will mislead whoever plans the next sub-project. Tick the six shipped items with the evidence (Terraform parser, Docker Compose parser, topology API endpoints, React Flow diagram, environment topology page, GitHub repo field), strike the Neo4j sync consumer with a pointer to `docs/decisions/2026-07-30-drop-neo4j.md`, and restate the remainder as the four sub-projects: environment comparison (this work), drift detection, GitHub App/OAuth + repository scanning, and env-topology SP4.

Record that SP4's machinery is complete and only the control is missing — `setGroupBy` in `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx:52` is currently dead code.

- [ ] **Step 4: Update `docs/plan.md` and `CLAUDE.md`**

`docs/plan.md` line 19 — the Phase 6 row still says "Terraform/React Flow + drift-vs-Production still pending", which is wrong about both Terraform and React Flow. Restate it as the four sub-projects with comparison done.

`CLAUDE.md` header — add Phase 6 sub-project 1 with the two decisions worth carrying: host **shape** not host identity, and a symmetric API with the reference applied in the UI. Bump the main-tip reference.

- [ ] **Step 5: Commit, push, open the PR**

- [ ] **Step 6: Confirm all four CI jobs pass before reporting done.** Do not report ready on a partial result.
