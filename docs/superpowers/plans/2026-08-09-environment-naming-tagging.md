# Phase 7 B2 — Naming & tagging conventions, and untagged quarantine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tenant declares what an environment's name must look like and which attributes it must carry; every environment is judged against that policy, and one failing for longer than a grace period reads as quarantined — a label and a filter, never a block.

**Architecture:** One new per-tenant config table (`environment_naming_policy`, one row per tenant, shaped like `RaidConfig`) plus one nullable column (`environment.name_compliant`). A single new service, `environment_compliance_service`, owns every regex decision in the codebase; the name verdict is **stored** because no regex is portable across SQLite and PostgreSQL, while the attribute half stays computed in SQL. Quarantine is derived on read from the stored verdict, `created_at` and the policy — there is no scheduler and no status column.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, pytest (dual engine: SQLite + PostgreSQL), React 18 + TypeScript + MUI DataGrid + Redux Toolkit, Vitest.

**Spec:** [../specs/2026-08-09-environment-naming-tagging-design.md](../specs/2026-08-09-environment-naming-tagging-design.md) — read it before Task 1. Every "why" below is recorded there.

## Global Constraints

- **B2 ADVISES; IT NEVER BLOCKS A BOOKING.** No booking is refused, transitioned or gated. The one refusal in the whole sub-project is a 422 on a **changed** environment name that fails the pattern.
- **Every filter runs in SQL, before the window.** A Python-side filter on a paged endpoint windows the page before the filter and returns quietly wrong results — see `docs/pagination.md`.
- **`re.fullmatch` is called in exactly one function** (`environment_compliance_service.name_matches`). No other module imports `re` for this purpose, and no regex is ever evaluated in SQL or in the browser.
- **`name_compliant IS NULL` means "no pattern applies" and counts as COMPLIANT** — never as unknown, never as failing.
- **"No selection" on a filter is an OMITTED KEY.** An empty `?compliance_gap=` is a 422. The frontend's no-selection value is `''` via `buildParams`; the string `'all'` must never enter these filters' vocabularies.
- **Soft deletes only** (`deleted_at`), `native_enum=False` on any enum column, `db.flush()` never `db.commit()` in services, `current_user.active_tenant_id` never `.tenant_id`.
- **Migrations are hand-written** (`op.create_table` / `op.add_column`), never `--autogenerate`.
- **Both engines, every task.** SQLite leg: `uv run pytest -q`. PostgreSQL leg: `TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q`.
- Backend commands run from `backend/` with `uv run`. Frontend from `frontend/` with `npx vitest run <path>`.
- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`), one commit per task minimum.

---

### Task 1: The `cf:<key>` JSON predicate, proven on both engines

The spec names this the **first** task on purpose: it is the only part of the design with no precedent in the codebase, and if `custom_fields[key]` does not compile cleanly on both engines the vocabulary must shrink to real columns only. Find out on day one.

**Files:**
- Create: `backend/app/services/environment_compliance_service.py`
- Test: `backend/tests/services/test_environment_compliance_predicates.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `custom_field_missing_clause(field_key: str) -> ColumnElement[bool]` — SQL true when `environment.custom_fields` lacks `field_key`, or holds null/empty-string for it.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_environment_compliance_predicates.py
"""The one part of B2 with no precedent in this codebase: reaching inside the
`custom_fields` JSON column from SQL. It compiles to `->>` on PostgreSQL and
`json_extract` on SQLite, so it is tested on both legs before anything is
built on top of it."""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services.environment_compliance_service import custom_field_missing_clause
from tests.factories import ensure_environment_tier


async def _env(db, tenant_id, name, custom_fields):
    tier = await ensure_environment_tier(db, tenant_id)
    env = Environment(
        name=name, tier_id=tier.id, tenant_id=tenant_id, custom_fields=custom_fields
    )
    db.add(env)
    await db.flush()
    return env


@pytest.mark.asyncio
async def test_missing_key_absent_null_and_blank_all_count_as_missing(
    db_session, test_tenant
):
    await _env(db_session, test_tenant.id, "absent", {"other": "x"})
    await _env(db_session, test_tenant.id, "explicit-null", {"cost_centre": None})
    await _env(db_session, test_tenant.id, "blank", {"cost_centre": "   "})
    await _env(db_session, test_tenant.id, "no-json-at-all", None)
    await _env(db_session, test_tenant.id, "present", {"cost_centre": "CC-1"})

    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("cost_centre"),
            )
        )
    ).scalars().all()

    assert sorted(rows) == ["absent", "blank", "explicit-null", "no-json-at-all"]


@pytest.mark.asyncio
async def test_a_numeric_value_counts_as_present(db_session, test_tenant):
    """A custom field of type `number` stores an int, not a string. Casting to
    text must not make 0 look absent — `0` is a supplied value."""
    await _env(db_session, test_tenant.id, "zero", {"seats": 0})
    rows = (
        await db_session.execute(
            select(Environment.name).where(
                Environment.tenant_id == test_tenant.id,
                custom_field_missing_clause("seats"),
            )
        )
    ).scalars().all()
    assert rows == []
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/services/test_environment_compliance_predicates.py -v`
Expected: FAIL — `ImportError: cannot import name 'custom_field_missing_clause'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# backend/app/services/environment_compliance_service.py
"""B2 — environment naming and tagging compliance.

This module owns EVERY regex decision in the application. The name verdict is
stored on `environment.name_compliant` rather than evaluated in SQL because no
regex is portable across both engines this app runs on, and a dialect-SQL match
would put three regex engines (Python at save, PostgreSQL's POSIX ARE, and a
Python callback on SQLite) behind one rule — engines that disagree on real
patterns, so a name refused at save could report compliant in the list.

The ATTRIBUTE half needs none of that and stays computed in SQL.
"""
from sqlalchemy import String, func, or_
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.environment import Environment


def custom_field_missing_clause(field_key: str) -> ColumnElement[bool]:
    """True when `custom_fields` does not supply a usable value for `field_key`.

    Absent, JSON null, and whitespace-only all count as missing; `0` and `false`
    do not — a `number` custom field storing zero is a supplied value, and
    `trim()` over the text form of `0` is `'0'`, which is non-empty.

    `Environment.custom_fields[field_key]` is dialect-compiled by SQLAlchemy:
    `->>` on PostgreSQL, `json_extract` on SQLite. `field_key` is a bound
    parameter, never interpolated.
    """
    value = Environment.custom_fields[field_key].as_string()
    return or_(
        Environment.custom_fields.is_(None),
        value.is_(None),
        func.trim(func.cast(value, String)) == "",
    )
```

- [ ] **Step 4: Run the tests on SQLite**

Run: `cd backend && uv run pytest tests/services/test_environment_compliance_predicates.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Run the same tests on PostgreSQL — this is the point of the task**

Run: `cd backend && TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest tests/services/test_environment_compliance_predicates.py -v`
Expected: PASS, 2 tests.

If the PostgreSQL leg fails and cannot be made to pass with a dialect-neutral expression, **stop and report**: the fallback recorded in the spec is to ship `required_attributes` as real columns only (`owner`, `expiry`, `operations_group`) and defer `cf:` keys, which changes Tasks 4, 6 and 8. Do not invent a Python-side workaround — that would move a filter out of SQL.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/environment_compliance_service.py backend/tests/services/test_environment_compliance_predicates.py
git commit -m "feat(b2): a dialect-portable 'custom field missing' SQL predicate"
```

---

### Task 2: Model and migration

**Files:**
- Create: `backend/app/db/models/environment_naming_policy.py`
- Create: `backend/app/db/migrations/versions/20260810_1000_envnamingpolicy_add_naming_policy.py`
- Modify: `backend/app/db/models/environment.py` (add `name_compliant`)
- Modify: `backend/app/db/models/__init__.py` (export the new model)
- Test: `backend/tests/test_environment_naming_policy_model.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EnvironmentNamingPolicy` with columns `tenant_id`, `is_enabled: bool`, `name_pattern: str | None`, `name_pattern_example: str | None`, `required_attributes: list`, `grace_days: int`, `effective_from: datetime`; and `Environment.name_compliant: bool | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_environment_naming_policy_model.py
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from tests.factories import ensure_environment_tier


@pytest.mark.asyncio
async def test_a_policy_defaults_to_disabled_with_no_rule(db_session, test_tenant):
    policy = EnvironmentNamingPolicy(tenant_id=test_tenant.id)
    db_session.add(policy)
    await db_session.flush()
    await db_session.refresh(policy)

    assert policy.is_enabled is False
    assert policy.name_pattern is None
    assert policy.required_attributes == []
    assert policy.grace_days == 14
    assert policy.effective_from is not None


@pytest.mark.asyncio
async def test_name_compliant_starts_null_meaning_no_pattern_applies(
    db_session, test_tenant
):
    """NULL is 'no pattern applies', not 'unknown' and not 'failing'. Every
    clause and every cell downstream treats it as compliant."""
    tier = await ensure_environment_tier(db_session, test_tenant.id)
    env = Environment(name="anything", tier_id=tier.id, tenant_id=test_tenant.id)
    db_session.add(env)
    await db_session.flush()
    await db_session.refresh(env)

    assert env.name_compliant is None


@pytest.mark.asyncio
async def test_one_policy_per_tenant(db_session, test_tenant):
    db_session.add(EnvironmentNamingPolicy(tenant_id=test_tenant.id))
    await db_session.flush()
    db_session.add(EnvironmentNamingPolicy(tenant_id=test_tenant.id))
    with pytest.raises(Exception):
        await db_session.flush()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest tests/test_environment_naming_policy_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db.models.environment_naming_policy'`.

- [ ] **Step 3: Write the model**

```python
# backend/app/db/models/environment_naming_policy.py
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EnvironmentNamingPolicy(Base):
    """B2 — one tenant's naming and tagging convention. One row per tenant.

    Shaped like `RaidConfig`, this codebase's existing per-tenant config table:
    `tenant_id` unique, no `deleted_at`. There is no DELETE path — `is_enabled`
    is the off switch, and deleting the row would throw away the pattern.
    """

    __tablename__ = "environment_naming_policy"

    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True, unique=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Null means "no naming rule, attributes only". Capped at 500 characters as
    # the first line of the ReDoS guard — see environment_compliance_service.
    name_pattern: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # A worked example, shown in the admin UI AND in the 422. Refused at save
    # if its own pattern rejects it, or the error message teaches a name that
    # will also be refused.
    name_pattern_example: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    # Vocabulary: 'owner', 'expiry', 'operations_group', and 'cf:<field_key>'.
    # 'tier' is deliberately NOT offered: environment.tier_id is already
    # nullable=False, so requiring it would be a check that can never fail — a
    # permanently-green row that reads as governance.
    required_attributes: Mapped[list] = mapped_column(
        JSON, nullable=False, default=list
    )
    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    # Bumped whenever `name_pattern` or `required_attributes` changes, in EITHER
    # direction — "stricter" is not a decidable property of a regex change, and
    # granting fresh grace for a relaxation is harmless. NOT bumped by an edit
    # to grace_days, is_enabled or the example: those do not change what is
    # being asked of an environment.
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return (
            f"<EnvironmentNamingPolicy(tenant_id={self.tenant_id}, "
            f"enabled={self.is_enabled})>"
        )
```

- [ ] **Step 4: Add the column to `Environment`**

In `backend/app/db/models/environment.py`, immediately after the `custom_fields` line in `class Environment`:

```python
    # B2 — the stored verdict of the tenant's naming pattern. NULL means "no
    # pattern applies" (no policy, disabled, or a null pattern), NOT "unknown"
    # and NOT "failing": every clause and every cell treats null as compliant.
    #
    # Stored rather than computed because no regex is portable across both
    # engines, and every filter here must run in SQL. Its whole invalidation
    # surface is: create_environment_record, update_environment (name changed),
    # environment_request_service fulfilment, and a policy write. A future
    # write path that sets `name` without going through those produces a lying
    # verdict — see test_environment_compliance_write_paths.py.
    name_compliant: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
```

Then export the model in `backend/app/db/models/__init__.py` alongside the others:

```python
from app.db.models.environment_naming_policy import EnvironmentNamingPolicy  # noqa: F401
```

- [ ] **Step 5: Write the migration by hand**

```python
# backend/app/db/migrations/versions/20260810_1000_envnamingpolicy_add_naming_policy.py
"""B2: the environment naming policy, and the stored name verdict

Revision ID: envnamingpolicy
Revises: contention
Create Date: 2026-08-10

Additive: one table, one nullable column, and NO BACKFILL AT ALL.

No tenant has a policy at migration time, so `environment.name_compliant` is
correctly NULL for every existing row — the column's null-means-no-pattern-
applies semantics are what make the backfill unnecessary rather than merely
deferred. Rows get their verdict from `recompute_tenant` the moment a policy is
first saved.
"""
import sqlalchemy as sa
from alembic import op

revision = "envnamingpolicy"
down_revision = "contention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "environment_naming_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Integer(),
            sa.ForeignKey("tenant.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("name_pattern", sa.String(length=500), nullable=True),
        sa.Column("name_pattern_example", sa.String(length=200), nullable=True),
        sa.Column(
            "required_attributes", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "grace_days", sa.Integer(), nullable=False, server_default=sa.text("14")
        ),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # Base's timestamps. Six tables shipped without these once and the
        # migration-built database was broken for months — see the hardening
        # programme.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_environment_naming_policy_tenant_id",
        "environment_naming_policy",
        ["tenant_id"],
    )
    op.add_column(
        "environment", sa.Column("name_compliant", sa.Boolean(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("environment", "name_compliant")
    op.drop_index(
        "ix_environment_naming_policy_tenant_id",
        table_name="environment_naming_policy",
    )
    op.drop_table("environment_naming_policy")
```

Check `Base` first (`backend/app/db/base.py`) and match its `created_at`/`updated_at` column definitions exactly — types, defaults and **timezone-awareness**. `tests/test_migration_schema_drift.py` compares only column NAME SETS, so it will pass a naive-vs-aware mismatch that would reach production.

- [ ] **Step 6: Run the tests and the drift guard on both engines**

```bash
cd backend
uv run pytest tests/test_environment_naming_policy_model.py tests/test_migration_schema_drift.py -v
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/test_environment_naming_policy_model.py tests/test_migration_schema_drift.py -v
```

Expected: PASS on both.

- [ ] **Step 7: Apply the migration to the dev database**

Run: `cd backend && alembic current && alembic upgrade head`
Expected: `current` shows `contention` before, `envnamingpolicy` after.

**Never run `alembic downgrade -1` against the dev database to test this** — it steps back from whatever the current head is and has already dropped `tenant_secret` and wiped a real GitHub token once.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models/environment_naming_policy.py backend/app/db/models/environment.py backend/app/db/models/__init__.py backend/app/db/migrations/versions/20260810_1000_envnamingpolicy_add_naming_policy.py backend/tests/test_environment_naming_policy_model.py
git commit -m "feat(b2): environment_naming_policy table and the stored name verdict"
```

---

### Task 3: The evaluator — pattern matching, validation, and the ReDoS guard

**Files:**
- Modify: `backend/app/services/environment_compliance_service.py`
- Test: `backend/tests/services/test_environment_compliance_evaluator.py`

**Interfaces:**
- Consumes: `custom_field_missing_clause` (Task 1).
- Produces:
  - `name_matches(pattern: str, name: str) -> bool`
  - `validate_pattern(pattern: str | None, example: str | None) -> None` — raises `HTTPException(422)`
  - `assert_name_allowed(policy, submitted: str, stored: str | None) -> None` — raises `HTTPException(422)`
  - `evaluate_name(policy, name: str) -> bool | None`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/services/test_environment_compliance_evaluator.py
import pytest
from fastapi import HTTPException

from app.db.models.environment_naming_policy import EnvironmentNamingPolicy
from app.services import environment_compliance_service as svc


def _policy(**kw) -> EnvironmentNamingPolicy:
    defaults = dict(
        tenant_id=1,
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    defaults.update(kw)
    return EnvironmentNamingPolicy(**defaults)


def test_a_pattern_anchors_by_default():
    """fullmatch, not search: a tenant writing `dev-.*` and having `xxdev-1`
    accepted is the likelier error."""
    assert svc.name_matches(r"dev-.*", "dev-1") is True
    assert svc.name_matches(r"dev-.*", "xxdev-1") is False


def test_evaluate_name_returns_none_when_no_pattern_applies():
    assert svc.evaluate_name(None, "anything") is None
    assert svc.evaluate_name(_policy(is_enabled=False), "nope") is None
    assert svc.evaluate_name(_policy(name_pattern=None), "nope") is None


def test_evaluate_name_judges_when_a_pattern_applies():
    assert svc.evaluate_name(_policy(), "payments-uat-01") is True
    assert svc.evaluate_name(_policy(), "Payments UAT 1") is False


def test_an_unchanged_bad_name_is_accepted():
    """Activating a policy must not freeze every non-conforming environment's
    next save. A full-form PATCH re-sending the stored name is accepted."""
    svc.assert_name_allowed(_policy(), submitted="legacy box", stored="legacy box")


def test_a_changed_name_that_still_fails_is_refused():
    with pytest.raises(HTTPException) as exc:
        svc.assert_name_allowed(_policy(), submitted="legacy box 2", stored="legacy box")
    assert exc.value.status_code == 422
    # The example is in the message, so the 422 teaches a name that works.
    assert "payments-uat-01" in exc.value.detail


def test_a_new_name_is_judged_against_the_pattern():
    with pytest.raises(HTTPException):
        svc.assert_name_allowed(_policy(), submitted="nope", stored=None)
    svc.assert_name_allowed(_policy(), submitted="payments-uat-01", stored=None)


def test_no_policy_refuses_nothing():
    svc.assert_name_allowed(None, submitted="anything at all", stored=None)
    svc.assert_name_allowed(_policy(is_enabled=False), submitted="!!!", stored=None)


def test_an_invalid_regex_is_refused_at_save():
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern("[unclosed", None)
    assert exc.value.status_code == 422


def test_a_pattern_longer_than_500_characters_is_refused():
    with pytest.raises(HTTPException):
        svc.validate_pattern("a" * 501, None)


def test_an_example_its_own_pattern_rejects_is_refused():
    with pytest.raises(HTTPException) as exc:
        svc.validate_pattern(r"[a-z]+-\d{2}", "NOT-A-MATCH")
    assert exc.value.status_code == 422
    assert "example" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_a_catastrophic_pattern_is_refused_by_the_probe():
    """The pattern runs in the shared server process, so one catastrophic
    pattern pins a worker for EVERY tenant and Python's `re` has no timeout."""
    with pytest.raises(HTTPException) as exc:
        await svc.validate_pattern_async(r"(a+)+$", None)
    assert exc.value.status_code == 422
    assert "too slow" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_an_ordinary_pattern_passes_the_probe():
    await svc.validate_pattern_async(r"[a-z]+-(dev|uat|prod)-\d{2}", "payments-uat-01")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest tests/services/test_environment_compliance_evaluator.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'name_matches'`.

- [ ] **Step 3: Implement the evaluator**

Append to `backend/app/services/environment_compliance_service.py`:

```python
import asyncio
import re
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, status

from app.db.models.environment_naming_policy import EnvironmentNamingPolicy

MAX_PATTERN_LENGTH = 500
# environment.name is String(200), so the probe string is a worst case a real
# name could actually reach.
_PROBE_STRING = "a" * 200
_PROBE_TIMEOUT_SECONDS = 0.25


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern:
    return re.compile(pattern)


def name_matches(pattern: str, name: str) -> bool:
    """THE one regex call site in this application.

    `fullmatch`, not `search`: a pattern anchors by default, because a tenant
    writing `dev-.*` and having `xxdev-1` accepted is the likelier error.
    """
    return _compiled(pattern).fullmatch(name or "") is not None


def _pattern_in_force(policy: Optional[EnvironmentNamingPolicy]) -> Optional[str]:
    if policy is None or not policy.is_enabled or not policy.name_pattern:
        return None
    return policy.name_pattern


def evaluate_name(
    policy: Optional[EnvironmentNamingPolicy], name: str
) -> Optional[bool]:
    """The verdict stored on `environment.name_compliant`.

    None means NO PATTERN APPLIES — not unknown, not failing.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None:
        return None
    return name_matches(pattern, name)


def assert_name_allowed(
    policy: Optional[EnvironmentNamingPolicy],
    submitted: str,
    stored: Optional[str],
) -> None:
    """The ONLY refusal in the whole of B2, and only for a CHANGED name.

    A full-form save re-sending an existing bad name is accepted — otherwise
    activating a policy freezes every non-conforming environment's next save,
    the same shape as A1's archived-FK-value carve-out.
    """
    pattern = _pattern_in_force(policy)
    if pattern is None or submitted == stored:
        return
    if name_matches(pattern, submitted):
        return
    example = policy.name_pattern_example
    hint = f" For example: '{example}'." if example else ""
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        f"'{submitted}' does not match this tenant's environment naming "
        f"convention ({pattern}).{hint}",
    )


def validate_pattern(pattern: Optional[str], example: Optional[str]) -> None:
    """Synchronous half of the save-time guard: length, compilability, and the
    example matching its own pattern."""
    if pattern is None:
        return
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A naming pattern may be at most {MAX_PATTERN_LENGTH} characters.",
        )
    try:
        _compiled(pattern)
    except re.error as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"That is not a valid regular expression: {e}",
        )
    if example is not None and not name_matches(pattern, example):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The example '{example}' does not match the pattern it illustrates. "
            "It appears in the error users see, so it has to be a name that works.",
        )


async def validate_pattern_async(
    pattern: Optional[str], example: Optional[str]
) -> None:
    """The full save-time guard, including the ReDoS probe.

    The pattern is tenant-admin-supplied and runs in the shared server process,
    so one catastrophic pattern pins a worker for EVERY tenant, and Python's
    `re` has no timeout. The probe runs the candidate against a 200-character
    adversarial string off the event loop and refuses it if it does not finish.

    This is a footgun guard, NOT a security boundary: a determined admin can
    still write a pattern that is slow but finishes. The recorded upgrade path
    is the `regex` package's per-match `timeout=`, which needs a dependency-
    audit entry.
    """
    validate_pattern(pattern, example)
    if pattern is None:
        return
    try:
        await asyncio.wait_for(
            asyncio.to_thread(name_matches, pattern, _PROBE_STRING),
            timeout=_PROBE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That pattern is too slow to evaluate safely — it backtracks "
            "catastrophically on a long name. Simplify nested quantifiers "
            "such as '(a+)+'.",
        )
```

- [ ] **Step 4: Run the tests on both engines**

```bash
cd backend
uv run pytest tests/services/test_environment_compliance_evaluator.py -v
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/services/test_environment_compliance_evaluator.py -v
```

Expected: PASS, 12 tests on each.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_compliance_service.py backend/tests/services/test_environment_compliance_evaluator.py
git commit -m "feat(b2): the one regex evaluator, with its save-time ReDoS guard"
```

---

### Task 4: Policy service and its API

**Files:**
- Create: `backend/app/api/v1/schemas/environment_naming_policy.py`
- Modify: `backend/app/services/environment_compliance_service.py`
- Modify: `backend/app/api/v1/tenant_admin_fields.py`
- Test: `backend/tests/test_environment_naming_policy_api.py`

**Interfaces:**
- Consumes: `evaluate_name`, `validate_pattern_async` (Task 3).
- Produces:
  - `load_policy(db, tenant_id) -> EnvironmentNamingPolicy | None`
  - `upsert_policy(db, tenant_id, *, is_enabled, name_pattern, name_pattern_example, required_attributes, grace_days) -> EnvironmentNamingPolicy`
  - `recompute_tenant(db, tenant_id, policy) -> int` (rows updated)
  - Endpoints `GET`/`PUT /api/v1/tenant/environment-naming-policy`
  - Schemas `EnvironmentNamingPolicyRead`, `EnvironmentNamingPolicyUpdate`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_environment_naming_policy_api.py
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from tests.factories import ensure_environment_tier, ensure_user, post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=["owner"],
        grace_days=14,
    )
    b.update(kw)
    return b


@pytest.mark.asyncio
async def test_get_returns_a_disabled_policy_before_one_is_saved(client, auth_headers):
    r = await client.get(POLICY_URL, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["is_enabled"] is False
    assert r.json()["name_pattern"] is None


@pytest.mark.asyncio
async def test_put_then_get_round_trips(client, auth_headers):
    r = await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    assert r.status_code == 200, r.text
    r = await client.get(POLICY_URL, headers=auth_headers)
    assert r.json()["name_pattern"] == r"[a-z]+-(dev|uat|prod)-\d{2}"
    assert r.json()["required_attributes"] == ["owner"]


@pytest.mark.asyncio
async def test_reads_are_open_to_any_tenant_member_writes_are_admin(
    client, auth_headers, db_session, test_tenant
):
    """B3a's rule: the reason an environment is flagged has to be legible to
    the person who has to fix it. Deliberately unlike /tenant/users."""
    viewer = await ensure_user(db_session, test_tenant.id, role="Viewer")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": viewer.username, "password": "testpass123", "tenant_slug": test_tenant.slug},
    )
    viewer_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get(POLICY_URL, headers=viewer_headers)).status_code == 200
    assert (
        await client.put(POLICY_URL, json=_body(), headers=viewer_headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_an_unknown_key_is_refused_not_silently_dropped(client, auth_headers):
    """POST /projects silently discarded priority_rank for the want of
    extra='forbid', and POST /tenant/lifecycle-templates still drops
    required_fields today."""
    r = await client.put(
        POLICY_URL, json=_body(grace_dayz=3), headers=auth_headers
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_negative_grace_days_is_refused(client, auth_headers):
    r = await client.put(POLICY_URL, json=_body(grace_days=-1), headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_required_attribute_is_refused(client, auth_headers):
    r = await client.put(
        POLICY_URL, json=_body(required_attributes=["tier"]), headers=auth_headers
    )
    assert r.status_code == 422
    assert "tier" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_saving_a_policy_recomputes_every_environment_in_the_tenant(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")

    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    rows = dict(
        (
            await db_session.execute(
                select(Environment.name, Environment.name_compliant).where(
                    Environment.tenant_id == test_tenant.id
                )
            )
        ).all()
    )
    assert rows["payments-uat-01"] is True
    assert rows["Legacy Box"] is False


@pytest.mark.asyncio
async def test_disabling_a_policy_returns_every_verdict_to_null(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    await client.put(POLICY_URL, json=_body(is_enabled=False), headers=auth_headers)

    verdicts = (
        await db_session.execute(
            select(Environment.name_compliant).where(
                Environment.tenant_id == test_tenant.id
            )
        )
    ).scalars().all()
    assert verdicts == [None]


@pytest.mark.asyncio
async def test_effective_from_is_bumped_by_a_rule_change_but_not_by_grace_days(
    client, auth_headers
):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    first = (await client.get(POLICY_URL, headers=auth_headers)).json()["effective_from"]

    await client.put(POLICY_URL, json=_body(grace_days=30), headers=auth_headers)
    after_grace = (await client.get(POLICY_URL, headers=auth_headers)).json()[
        "effective_from"
    ]
    assert after_grace == first, "grace_days does not change what is asked of an environment"

    await client.put(
        POLICY_URL, json=_body(grace_days=30, name_pattern=r"[a-z]+-\d{2}",
                               name_pattern_example="payments-01"),
        headers=auth_headers,
    )
    after_pattern = (await client.get(POLICY_URL, headers=auth_headers)).json()[
        "effective_from"
    ]
    assert after_pattern > first


@pytest.mark.asyncio
async def test_a_catastrophic_pattern_is_refused_by_the_endpoint(client, auth_headers):
    r = await client.put(
        POLICY_URL,
        json=_body(name_pattern=r"(a+)+$", name_pattern_example=None),
        headers=auth_headers,
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd backend && uv run pytest tests/test_environment_naming_policy_api.py -v`
Expected: FAIL — 404 on the URL, since the route does not exist.

- [ ] **Step 3: Write the schemas**

```python
# backend/app/api/v1/schemas/environment_naming_policy.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# 'tier' is deliberately absent: environment.tier_id is already nullable=False,
# so requiring it would be a check that can never fail.
FIXED_ATTRIBUTES = {"owner", "expiry", "operations_group"}
CUSTOM_FIELD_PREFIX = "cf:"


class EnvironmentNamingPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    is_enabled: bool
    name_pattern: Optional[str] = None
    name_pattern_example: Optional[str] = None
    required_attributes: list[str] = []
    grace_days: int
    effective_from: datetime


class EnvironmentNamingPolicyUpdate(BaseModel):
    # forbid: POST /projects silently discarded priority_rank for the want of
    # exactly this, and a dropped key here would leave an admin believing a
    # rule is in force that is not.
    model_config = ConfigDict(extra="forbid")

    is_enabled: bool
    name_pattern: Optional[str] = Field(default=None, max_length=500)
    name_pattern_example: Optional[str] = Field(default=None, max_length=200)
    required_attributes: list[str] = []
    grace_days: int = Field(default=14, ge=0, le=365)
```

- [ ] **Step 4: Write the service functions**

Append to `backend/app/services/environment_compliance_service.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.environment_naming_policy import (
    CUSTOM_FIELD_PREFIX,
    FIXED_ATTRIBUTES,
)
from app.services.custom_field_service import list_definitions


async def load_policy(
    db: AsyncSession, tenant_id: int
) -> Optional[EnvironmentNamingPolicy]:
    return (
        await db.execute(
            select(EnvironmentNamingPolicy).where(
                EnvironmentNamingPolicy.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def _assert_attributes_known(
    db: AsyncSession, tenant_id: int, attributes: list[str]
) -> None:
    """Every entry is either one of the three fixed attributes or a `cf:` key
    this tenant actually defines. A typo'd key would otherwise mark the whole
    estate non-compliant against a field that does not exist."""
    defined = {
        d.field_key
        for d in await list_definitions(db, tenant_id, "environment")
    }
    for attr in attributes:
        if attr in FIXED_ATTRIBUTES:
            continue
        if attr.startswith(CUSTOM_FIELD_PREFIX):
            key = attr[len(CUSTOM_FIELD_PREFIX):]
            if key in defined:
                continue
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"'{key}' is not a custom field defined for environments in "
                "this tenant.",
            )
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{attr}' is not an attribute a naming policy can require. "
            f"Use one of {sorted(FIXED_ATTRIBUTES)}, or 'cf:<field_key>'. "
            "Tier is always required by the schema, so it cannot be listed here.",
        )


async def upsert_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    is_enabled: bool,
    name_pattern: Optional[str],
    name_pattern_example: Optional[str],
    required_attributes: list[str],
    grace_days: int,
) -> EnvironmentNamingPolicy:
    await validate_pattern_async(name_pattern, name_pattern_example)
    await _assert_attributes_known(db, tenant_id, required_attributes)

    policy = await load_policy(db, tenant_id)
    if policy is None:
        policy = EnvironmentNamingPolicy(tenant_id=tenant_id)
        db.add(policy)
        rule_changed = bool(name_pattern) or bool(required_attributes)
    else:
        rule_changed = (
            policy.name_pattern != name_pattern
            or list(policy.required_attributes or []) != list(required_attributes)
        )

    policy.is_enabled = is_enabled
    policy.name_pattern = name_pattern
    policy.name_pattern_example = name_pattern_example
    policy.required_attributes = list(required_attributes)
    policy.grace_days = grace_days
    if rule_changed:
        # Bumped in EITHER direction: "stricter" is not decidable for a regex
        # change, and granting fresh grace for a relaxation is harmless.
        # Deliberately NOT bumped by grace_days, is_enabled or the example.
        policy.effective_from = datetime.now(timezone.utc)

    await db.flush()
    await recompute_tenant(db, tenant_id, policy)
    await db.refresh(policy)
    return policy


async def recompute_tenant(
    db: AsyncSession, tenant_id: int, policy: Optional[EnvironmentNamingPolicy]
) -> int:
    """Re-evaluate every live environment's stored name verdict.

    Bounded: one tenant's environments, one flush. This is one of only four
    things that may write `name_compliant` — see the module docstring.
    """
    envs = (
        await db.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    for env in envs:
        env.name_compliant = evaluate_name(policy, env.name)
    await db.flush()
    return len(envs)
```

Add `from datetime import datetime, timezone` to the module's imports.

- [ ] **Step 5: Wire the endpoints**

In `backend/app/api/v1/tenant_admin_fields.py`, add the import and the two routes below the raid-config pair:

```python
from app.core.security import get_current_user
from app.services import environment_compliance_service
from app.api.v1.schemas.environment_naming_policy import (
    EnvironmentNamingPolicyRead,
    EnvironmentNamingPolicyUpdate,
)


@router.get("/environment-naming-policy", response_model=EnvironmentNamingPolicyRead)
async def get_environment_naming_policy(
    db: AsyncSession = Depends(get_db),
    # Reads are open to any tenant member; only writes are Admin. The reason an
    # environment is flagged has to be legible to whoever must fix it — B3a's
    # rule, deliberately unlike /tenant/users, which really is admin-gated.
    current_user=Depends(get_current_user),
):
    policy = await environment_compliance_service.load_policy(
        db, current_user.active_tenant_id
    )
    if policy is None:
        # A tenant that has never saved one reads as "no rule in force" rather
        # than 404 — the UI has a form to render either way.
        return EnvironmentNamingPolicyRead(
            is_enabled=False,
            name_pattern=None,
            name_pattern_example=None,
            required_attributes=[],
            grace_days=14,
            effective_from=datetime.now(timezone.utc),
        )
    return policy


@router.put("/environment-naming-policy", response_model=EnvironmentNamingPolicyRead)
async def put_environment_naming_policy(
    data: EnvironmentNamingPolicyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_compliance_service.upsert_policy(
        db,
        current_user.active_tenant_id,
        is_enabled=data.is_enabled,
        name_pattern=data.name_pattern,
        name_pattern_example=data.name_pattern_example,
        required_attributes=data.required_attributes,
        grace_days=data.grace_days,
    )
```

Add `from datetime import datetime, timezone` at the top of that file.

- [ ] **Step 6: Run the tests on both engines**

```bash
cd backend
uv run pytest tests/test_environment_naming_policy_api.py -v
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/test_environment_naming_policy_api.py -v
```

Expected: PASS, 10 tests on each. If `ensure_user`'s signature differs from the test's use, read `backend/tests/factories.py` and match it rather than changing the factory.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/schemas/environment_naming_policy.py backend/app/services/environment_compliance_service.py backend/app/api/v1/tenant_admin_fields.py backend/tests/test_environment_naming_policy_api.py
git commit -m "feat(b2): GET/PUT the tenant environment naming policy"
```

---

### Task 5: Wire the verdict into every write path

This task closes the one real liability of a stored derived value. Its test is the sharpest in the plan.

**Files:**
- Modify: `backend/app/services/environment_service.py` (`create_environment_record`, `update_environment`)
- Modify: `backend/app/services/environment_request_service.py` (fulfilment, and the submit-time check)
- Test: `backend/tests/services/test_environment_compliance_write_paths.py`

**Interfaces:**
- Consumes: `load_policy`, `evaluate_name`, `assert_name_allowed` (Tasks 3–4).
- Produces: no new public functions. `Environment.name_compliant` is correct after every write.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/services/test_environment_compliance_write_paths.py
"""The stored verdict's integrity.

A verdict that nothing recomputes is worse than no verdict, so this drives an
environment through EVERY write path and asserts the stored value equals a
freshly computed one each time.
"""
import pytest
from sqlalchemy import select

from app.db.models.environment import Environment
from app.services import environment_compliance_service as svc
from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"
PATTERN = r"[a-z]+-(dev|uat|prod)-\d{2}"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=PATTERN,
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    b.update(kw)
    return b


async def _assert_verdict_is_honest(db_session, tenant_id):
    """Every stored verdict equals what the evaluator says right now."""
    policy = await svc.load_policy(db_session, tenant_id)
    envs = (
        await db_session.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id, Environment.deleted_at.is_(None)
            )
        )
    ).scalars().all()
    for env in envs:
        assert env.name_compliant == svc.evaluate_name(policy, env.name), (
            f"stored verdict for '{env.name}' is stale"
        )


@pytest.mark.asyncio
async def test_create_evaluates_the_new_name(
    client, auth_headers, db_session, test_tenant
):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    await post_environment(client, auth_headers, "payments-uat-01")
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_a_rename_re_evaluates(client, auth_headers, db_session, test_tenant):
    r = await post_environment(client, auth_headers, "payments-uat-01")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "payments-prod-02"},
        headers=auth_headers,
    )
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_a_full_form_save_with_an_unchanged_bad_name_is_accepted(
    client, auth_headers, db_session, test_tenant
):
    """Activating a policy must not freeze the estate."""
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    saved = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "Legacy Box", "description": "still here"},
        headers=auth_headers,
    )
    assert saved.status_code == 200, saved.text
    await _assert_verdict_is_honest(db_session, test_tenant.id)


@pytest.mark.asyncio
async def test_changing_a_bad_name_to_another_bad_name_is_refused(
    client, auth_headers
):
    r = await post_environment(client, auth_headers, "Legacy Box")
    env_id = r.json()["id"]
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    refused = await client.patch(
        f"/api/v1/environments/{env_id}",
        json={"name": "Legacy Box 2"},
        headers=auth_headers,
    )
    assert refused.status_code == 422
    assert "payments-uat-01" in refused.json()["detail"]


@pytest.mark.asyncio
async def test_creating_a_non_conforming_environment_is_refused(client, auth_headers):
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    r = await post_environment(client, auth_headers, "Nope")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_policy_change_re_evaluates_everything(
    client, auth_headers, db_session, test_tenant
):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "billing-dev-07")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    await client.put(
        POLICY_URL,
        json=_body(name_pattern=r"payments-.*", name_pattern_example="payments-x"),
        headers=auth_headers,
    )
    await _assert_verdict_is_honest(db_session, test_tenant.id)
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd backend && uv run pytest tests/services/test_environment_compliance_write_paths.py -v`
Expected: FAIL — the verdicts are all `None` because nothing sets them yet.

- [ ] **Step 3: Wire `create_environment_record`**

In `backend/app/services/environment_service.py`, inside `create_environment_record`, after the existing `await _validate_client_foreign_keys(...)` call and before `env = Environment(...)`:

```python
    policy = await environment_compliance_service.load_policy(db, tenant_id)
    environment_compliance_service.assert_name_allowed(policy, name, None)
```

and add `name_compliant=environment_compliance_service.evaluate_name(policy, name),` to the `Environment(...)` constructor call. Add the import at the top of the module:

```python
from app.services import environment_compliance_service
```

- [ ] **Step 4: Wire `update_environment`**

In `update_environment`, inside the existing `if data.name is not None and data.name != env.name:` block — after the duplicate-name check that is already there — add the compliance refusal and the re-evaluation:

```python
        policy = await environment_compliance_service.load_policy(db, tenant_id)
        # Only a CHANGED name is judged: this branch is already guarded by
        # `data.name != env.name`, so a full-form save re-sending the stored
        # name never reaches here.
        environment_compliance_service.assert_name_allowed(policy, data.name, env.name)
        env.name = data.name
        env.name_compliant = environment_compliance_service.evaluate_name(
            policy, data.name
        )
```

Read the surrounding code first: if `env.name = data.name` is already assigned further down that function, move it here rather than assigning twice.

- [ ] **Step 5: Wire request fulfilment — and make sure it cannot 422**

In `backend/app/services/environment_request_service.py`, at the fulfilment site (around line 699, the second `Environment(...)` construction in the codebase), add the verdict but **not** the refusal:

```python
    # B2: fulfilment RECORDS the verdict and never refuses. An approved request
    # that cannot be fulfilled is an unrecoverable state — the exact class B3b
    # produced twice. The pattern is checked at SUBMIT time instead, below.
    policy = await environment_compliance_service.load_policy(db, tenant_id)
    ...
    env = Environment(
        ...,
        name_compliant=environment_compliance_service.evaluate_name(
            policy, req.proposed_name
        ),
    )
```

Then find the submit transition (the one whose target is the `submitted` state) and add the refusal there, so a request naming a non-conforming environment is caught while it is still correctable:

```python
    if req.proposed_name:
        policy = await environment_compliance_service.load_policy(db, tenant_id)
        environment_compliance_service.assert_name_allowed(
            policy, req.proposed_name, None
        )
```

Add `from app.services import environment_compliance_service` to that module's imports.

- [ ] **Step 6: Add the fulfilment guard test**

Append to `backend/tests/services/test_environment_compliance_write_paths.py`:

```python
@pytest.mark.asyncio
async def test_fulfilling_an_approved_request_never_422s_on_the_naming_rule(
    client, auth_headers, db_session, test_tenant
):
    """An approved request that cannot be fulfilled is an unrecoverable state —
    B3b produced that shape twice. Fulfilment records the verdict; it never
    refuses. The check belongs at submit time, while the name is correctable.
    """
    from tests.factories import ensure_environment_request

    req = await ensure_environment_request(
        db_session, test_tenant.id, proposed_name="Not Conforming At All"
    )
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    from app.services import environment_request_service

    env = await environment_request_service.fulfil_request(
        db_session, req.id, test_tenant.id
    )
    assert env is not None
    assert env.name_compliant is False
```

Read `backend/tests/factories.py::ensure_environment_request` and `environment_request_service` first, and adjust the call to the real signatures — including how a request reaches the approved state — rather than changing either to fit this snippet.

- [ ] **Step 7: Run the whole environment suite on both engines**

```bash
cd backend
uv run pytest tests/services/test_environment_compliance_write_paths.py tests/ -k "environment" -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/services/test_environment_compliance_write_paths.py tests/ -k "environment" -q
```

Expected: PASS. Existing environment tests must stay green — no policy exists in those fixtures, so every verdict stays `None` and nothing is refused.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/environment_service.py backend/app/services/environment_request_service.py backend/tests/services/test_environment_compliance_write_paths.py
git commit -m "feat(b2): evaluate the name verdict on every environment write path"
```

---

### Task 6: The two verdicts, the filters, and the response fields

**Files:**
- Modify: `backend/app/services/environment_compliance_service.py`
- Modify: `backend/app/services/environment_service.py` (`list_environments`, `EnvironmentView`)
- Modify: `backend/app/api/v1/schemas/environment.py` (`EnvironmentResponse`, `from_view`)
- Modify: `backend/app/api/v1/environments.py` (query params, `ENVIRONMENT_SORTS`)
- Test: `backend/tests/services/test_environment_compliance_filters.py`

**Interfaces:**
- Consumes: `custom_field_missing_clause`, `load_policy` (Tasks 1, 4).
- Produces:
  - `noncompliance_clause(policy) -> ColumnElement[bool]`
  - `quarantine_clause(policy, now) -> ColumnElement[bool]`
  - `gaps_for_environments(envs: list[Environment], policy) -> dict[int, list[str]]`
  - `quarantined_ids(db, tenant_id, policy, now, env_ids: list[int]) -> set[int]`
  - `app.core.day_boundaries.expiry_boundary(now)` — moved here in Step 0, still importable from `contention_service`
  - `EnvironmentView.quarantined: bool`, `EnvironmentView.compliance_gaps: list[str]`
  - `EnvironmentResponse.name_compliant`, `.quarantined`, `.compliance_gaps`
  - `GET /environments?compliance_gap=&quarantined=`

- [ ] **Step 0: Move `expiry_boundary` out of `contention_service` first — there is a circular import here**

`contention_service` imports `environment_service` (line 40), and this task makes `environment_service` import `environment_compliance_service`. If the compliance service then imports `expiry_boundary` from `contention_service`, the cycle is:

```
environment_service → environment_compliance_service → contention_service → environment_service
```

Do **not** duplicate the helper to dodge it. **A DEADLINE IS A DAY** must keep exactly one owner — A4 wrote a 12-line docstring on that function explaining what happened when the rule was applied inconsistently, and two copies is how it becomes inconsistent again.

Move it to `backend/app/core/day_boundaries.py`:

```python
# backend/app/core/day_boundaries.py
"""The one place that decides A DEADLINE IS A DAY, NOT AN INSTANT.

Extracted from contention_service when B2 needed the same rule for its grace
period and importing it there would have closed an import cycle. The reasoning
lives in the function's docstring; do not add a second copy of this rule.
"""
from datetime import datetime, timezone


def expiry_boundary(now: datetime) -> datetime:
    ...  # move the body and the full docstring across verbatim
```

Then in `contention_service`, replace the definition with `from app.core.day_boundaries import expiry_boundary` — keeping the name importable from there, since existing tests and callers reference it.

Run the A4 suite to prove the move changed nothing:

```bash
cd backend && uv run pytest tests/test_contention_verdict.py tests/test_contention_escalation.py -q
```

Expected: PASS, unchanged counts. Commit this move on its own:

```bash
git add backend/app/core/day_boundaries.py backend/app/services/contention_service.py
git commit -m "refactor(b2): move expiry_boundary to app.core so B2 can share A4's day rule"
```

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/services/test_environment_compliance_filters.py
from datetime import datetime, timedelta, timezone

import pytest

from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"
ENVS_URL = "/api/v1/environments/"


def _body(**kw):
    b = dict(
        is_enabled=True,
        name_pattern=r"[a-z]+-(dev|uat|prod)-\d{2}",
        name_pattern_example="payments-uat-01",
        required_attributes=[],
        grace_days=14,
    )
    b.update(kw)
    return b


async def _names(client, headers, **params):
    r = await client.get(ENVS_URL, params=params, headers=headers)
    assert r.status_code == 200, r.text
    return sorted(e["name"] for e in r.json())


@pytest.mark.asyncio
async def test_with_no_policy_nothing_is_in_gap_and_nothing_is_quarantined(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Anything At All")
    assert await _names(client, auth_headers, compliance_gap="true") == []
    assert await _names(client, auth_headers, compliance_gap="false") == ["Anything At All"]
    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_true_and_false_partition_the_estate(client, auth_headers):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)

    in_gap = await _names(client, auth_headers, compliance_gap="true")
    clean = await _names(client, auth_headers, compliance_gap="false")
    everything = await _names(client, auth_headers)
    assert in_gap == ["Legacy Box"]
    assert sorted(in_gap + clean) == everything, "no row may be invisible to both"


@pytest.mark.asyncio
async def test_an_empty_filter_value_is_a_422_not_an_ignored_param(
    client, auth_headers
):
    r = await client.get(ENVS_URL, params={"compliance_gap": ""}, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_a_missing_required_attribute_is_a_gap(client, auth_headers):
    """The name conforms; the attribute does not."""
    await post_environment(client, auth_headers, "payments-uat-01", expires_at=None)
    await client.put(
        POLICY_URL, json=_body(required_attributes=["expiry"]), headers=auth_headers
    )
    assert await _names(client, auth_headers, compliance_gap="true") == [
        "payments-uat-01"
    ]


@pytest.mark.asyncio
async def test_a_null_verdict_counts_as_compliant_under_a_live_policy(
    client, auth_headers
):
    """A policy with required attributes but NO pattern leaves every verdict
    NULL while the policy is enabled. NULL means 'no pattern applies' and
    counts as COMPLIANT — writing the clause as `.is_not(True)` instead of
    `.is_(False)` puts the whole estate in gap and this is the only test that
    sees it."""
    await post_environment(client, auth_headers, "Anything At All")
    await client.put(
        POLICY_URL,
        json=_body(
            name_pattern=None, name_pattern_example=None, required_attributes=["owner"]
        ),
        headers=auth_headers,
    )
    # The environment has an owner (post_environment supplies one), so the only
    # thing that could put it in gap is a mis-read NULL verdict.
    assert await _names(client, auth_headers, compliance_gap="true") == []


@pytest.mark.asyncio
async def test_nothing_is_quarantined_while_the_policy_is_younger_than_grace(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=14), headers=auth_headers)
    assert await _names(client, auth_headers, compliance_gap="true") == ["Legacy Box"]
    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_quarantine_bites_once_grace_has_elapsed(
    client, auth_headers, db_session, test_tenant
):
    from app.services import environment_compliance_service as svc

    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=1), headers=auth_headers)

    policy = await svc.load_policy(db_session, test_tenant.id)
    policy.effective_from = datetime.now(timezone.utc) - timedelta(days=30)
    await db_session.flush()

    assert await _names(client, auth_headers, quarantined="true") == ["Legacy Box"]


@pytest.mark.asyncio
async def test_a_deadline_is_a_day(client, auth_headers, db_session, test_tenant):
    """A4's class of bug: at instant precision an environment created at 15:00
    loses most of its last grace day, and the filter hides the rows closest to
    their deadline. Created 15:00 on day 0 with grace_days=1 is NOT quarantined
    at 09:00 on day 1."""
    from app.db.models.environment import Environment
    from app.services import environment_compliance_service as svc
    from sqlalchemy import select

    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(grace_days=1), headers=auth_headers)

    now = datetime.now(timezone.utc)
    env = (
        await db_session.execute(
            select(Environment).where(Environment.name == "Legacy Box")
        )
    ).scalar_one()
    env.created_at = (now - timedelta(days=1)).replace(hour=15, minute=0, second=0)
    policy = await svc.load_policy(db_session, test_tenant.id)
    policy.effective_from = now - timedelta(days=30)
    await db_session.flush()

    assert await _names(client, auth_headers, quarantined="true") == []


@pytest.mark.asyncio
async def test_the_response_carries_the_verdict_and_its_messages(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(POLICY_URL, json=_body(), headers=auth_headers)
    row = (await client.get(ENVS_URL, headers=auth_headers)).json()[0]
    assert row["name_compliant"] is False
    assert row["quarantined"] is False
    assert any("naming convention" in m for m in row["compliance_gaps"])


@pytest.mark.asyncio
async def test_quarantined_is_not_sortable(client, auth_headers):
    """It is computed from a column plus the policy, so there is no single
    column to order by — docs/pagination.md's permanently-unsortable set."""
    r = await client.get(ENVS_URL, params={"sort_by": "quarantined"}, headers=auth_headers)
    assert r.status_code == 422
```

- [ ] **Step 2: Run and watch them fail**

Run: `cd backend && uv run pytest tests/services/test_environment_compliance_filters.py -v`
Expected: FAIL — unknown query parameters are ignored, so the filter tests fail on content, and `name_compliant` is absent from the response.

- [ ] **Step 3: Implement the two clauses and the message builder**

Append to `backend/app/services/environment_compliance_service.py`:

```python
from datetime import timedelta

from sqlalchemy import and_, false, true

from app.core.day_boundaries import expiry_boundary  # moved in Step 0

_ATTRIBUTE_CLAUSES = {
    "owner": lambda: Environment.owner_user_id.is_(None),
    "expiry": lambda: Environment.expires_at.is_(None),
    "operations_group": lambda: Environment.operations_group_id.is_(None),
}

_ATTRIBUTE_LABELS = {
    "owner": "no named owner",
    "expiry": "no expiry date",
    "operations_group": "no operating team",
}


def _attribute_clauses(policy: EnvironmentNamingPolicy) -> list:
    clauses = []
    for attr in policy.required_attributes or []:
        if attr in _ATTRIBUTE_CLAUSES:
            clauses.append(_ATTRIBUTE_CLAUSES[attr]())
        elif attr.startswith(CUSTOM_FIELD_PREFIX):
            clauses.append(custom_field_missing_clause(attr[len(CUSTOM_FIELD_PREFIX):]))
    return clauses


def noncompliance_clause(
    policy: Optional[EnvironmentNamingPolicy],
) -> ColumnElement[bool]:
    """SQL true when an environment fails the policy.

    NO GRACE APPLIES HERE — an environment is in gap the moment the policy says
    so. Quarantine is the subset that has been in gap long enough.

    Returns a false literal when no policy is in force, rather than leaving the
    caller to skip the clause: no caller can then forget.
    """
    if policy is None or not policy.is_enabled:
        return false()
    # `is_(False)` and not `.is_not(True)`: NULL means NO PATTERN APPLIES and
    # counts as compliant.
    clauses = [Environment.name_compliant.is_(False)] + _attribute_clauses(policy)
    return or_(*clauses) if clauses else false()


def quarantine_clause(
    policy: Optional[EnvironmentNamingPolicy], now: datetime
) -> ColumnElement[bool]:
    """In gap AND grace has fully elapsed.

    `effective_from` and `grace_days` are scalars from a single policy row, so
    the policy-age half is a plain Python comparison: while the policy is
    younger than the grace period, NOTHING is quarantined and there is no
    clause to run at all.

    Day-granular via A4's `expiry_boundary`. A DEADLINE IS A DAY: at instant
    precision an environment created at 15:00 loses most of its last grace day,
    and — worse — the filter then hides the rows closest to their deadline.
    """
    if policy is None or not policy.is_enabled:
        return false()
    cutoff = expiry_boundary(now) - timedelta(days=policy.grace_days)
    if policy.effective_from > cutoff:
        return false()
    return and_(noncompliance_clause(policy), Environment.created_at <= cutoff)


def gaps_for_environments(
    envs: list[Environment], policy: Optional[EnvironmentNamingPolicy]
) -> dict[int, list[str]]:
    """Rendered gap messages for a WHOLE PAGE, keyed by environment id.

    Once per RESPONSE, never once per row. There is deliberately no per-row
    public helper: A3 shipped one as a cross-check and had to write "no
    production caller" in its docstring to stop a 50-row page costing ~150
    queries. Every input here is already on the selected row, so the batch form
    costs nothing extra and the per-row form would only invite the mistake.
    """
    if policy is None or not policy.is_enabled:
        return {env.id: [] for env in envs}

    out: dict[int, list[str]] = {}
    for env in envs:
        messages: list[str] = []
        if env.name_compliant is False:
            example = policy.name_pattern_example
            hint = f" (for example: '{example}')" if example else ""
            messages.append(
                f"The name does not match this tenant's naming convention{hint}"
            )
        for attr in policy.required_attributes or []:
            if attr in _ATTRIBUTE_LABELS:
                if _is_attribute_missing(env, attr):
                    messages.append(_ATTRIBUTE_LABELS[attr])
            elif attr.startswith(CUSTOM_FIELD_PREFIX):
                key = attr[len(CUSTOM_FIELD_PREFIX):]
                value = (env.custom_fields or {}).get(key)
                if value is None or str(value).strip() == "":
                    messages.append(f"no {key.replace('_', ' ')}")
        out[env.id] = messages
    return out


def _is_attribute_missing(env: Environment, attr: str) -> bool:
    """The Python mirror of `_ATTRIBUTE_CLAUSES`, for wording a message over a
    row the SQL clause already selected. These two must change together."""
    if attr == "owner":
        return env.owner_user_id is None
    if attr == "expiry":
        return env.expires_at is None
    if attr == "operations_group":
        return env.operations_group_id is None
    return False
```

- [ ] **Step 4: Thread it through `list_environments` and the view**

In `backend/app/services/environment_service.py`:

1. Add `compliance_gap: Optional[bool] = None` and `quarantined: Optional[bool] = None` to `list_environments`' signature.
2. Load the policy once, at the top of the function body: `policy = await environment_compliance_service.load_policy(db, tenant_id)`.
3. Apply the filters in SQL alongside the existing ones:

```python
    now = datetime.now(timezone.utc)
    if compliance_gap is not None:
        clause = environment_compliance_service.noncompliance_clause(policy)
        query = query.where(clause if compliance_gap else ~clause)
    if quarantined is not None:
        clause = environment_compliance_service.quarantine_clause(policy, now)
        query = query.where(clause if quarantined else ~clause)
```

4. Add `quarantined: bool` and `compliance_gaps: list[str]` to the `EnvironmentView` dataclass, and populate them after the rows come back — one `gaps_for_environments` call for the page, and the quarantine verdict evaluated per row from the same scalars the clause used:

```python
    envs = [row[0] for row in rows]
    gaps = environment_compliance_service.gaps_for_environments(envs, policy)
    quarantined_ids = await environment_compliance_service.quarantined_ids(
        db, tenant_id, policy, now, [e.id for e in envs]
    )
```

Add that last helper to the compliance service — one query over the page's ids, so the rendered flag and the filter cannot disagree:

```python
async def quarantined_ids(
    db: AsyncSession,
    tenant_id: int,
    policy: Optional[EnvironmentNamingPolicy],
    now: datetime,
    env_ids: list[int],
) -> set[int]:
    """Which of these environments are quarantined, decided by the SAME clause
    the filter uses. One clock per request decides both, so a filtered row and
    its rendered chip can never disagree — A4's rule."""
    if not env_ids or policy is None or not policy.is_enabled:
        return set()
    rows = (
        await db.execute(
            select(Environment.id).where(
                Environment.id.in_(env_ids),
                Environment.tenant_id == tenant_id,
                quarantine_clause(policy, now),
            )
        )
    ).scalars().all()
    return set(rows)
```

Do the same in `get_environment_view` so the detail page agrees with the list.

- [ ] **Step 5: Add the response fields**

In `backend/app/api/v1/schemas/environment.py`, add to `EnvironmentResponse` after `reserved_now`:

```python
    # B2. `name_compliant` is a real column and therefore sortable; NULL means
    # no pattern applies and counts as compliant.
    name_compliant: Optional[bool] = None
    # Derived from that column plus created_at and the policy, so it is
    # PERMANENTLY sortable: false — docs/pagination.md's unsortable set.
    quarantined: bool = False
    compliance_gaps: list[str] = []
```

and to `from_view`:

```python
            name_compliant=env.name_compliant,
            quarantined=view.quarantined,
            compliance_gaps=view.compliance_gaps,
```

- [ ] **Step 6: Add the query parameters**

In `backend/app/api/v1/environments.py`, add to `list_environments`' signature, beside `governance_gap`:

```python
    compliance_gap: Optional[bool] = Query(
        None,
        description=(
            "Fails the tenant's naming/tagging policy. No selection is an "
            "OMITTED key — an empty value is a 422, and `false` is the exact "
            "complement (compliant plus every environment no policy covers)."
        ),
    ),
    quarantined: Optional[bool] = Query(
        None, description="In gap, and grace has fully elapsed. Advisory only."
    ),
```

and pass both through to the service. Do **not** add either to `ENVIRONMENT_SORTS`: `quarantined` is computed, and while `name_compliant` is a real column, leave it out until a grid column actually asks to sort on it.

- [ ] **Step 6b: Guard the duplication — the three-way agreement test**

`_is_attribute_missing` is a Python mirror of `_ATTRIBUTE_CLAUSES`, and Task 7's preview will be a third evaluation of the same rule. The spec cites A3's rule against exactly this ("A1 shipped a count and a list, written three tasks apart, that disagreed two ways"), and the owner's ruling is: **keep all three, and guard them with a test that fails the moment they disagree.**

Append to `backend/tests/services/test_environment_compliance_filters.py`:

```python
@pytest.mark.asyncio
async def test_the_sql_clause_and_the_python_mirror_agree_row_for_row(
    client, auth_headers, db_session, test_tenant
):
    """Three evaluations of one rule — the SQL filter, the message-wording
    mirror, and (from Task 7) the preview — must never disagree. A1 shipped a
    count and a list, written three tasks apart, that disagreed two ways.
    """
    from sqlalchemy import select
    from app.db.models.environment import Environment
    from app.services import environment_compliance_service as svc

    # A matrix: conforming/not × owner present/absent × expiry present/absent.
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "payments-dev-02", expires_at=None)
    await post_environment(client, auth_headers, "Legacy Box")
    await post_environment(client, auth_headers, "Another Old One", expires_at=None)

    await client.put(
        POLICY_URL,
        json=_body(required_attributes=["expiry"]),
        headers=auth_headers,
    )

    policy = await svc.load_policy(db_session, test_tenant.id)
    envs = (
        await db_session.execute(
            select(Environment).where(Environment.tenant_id == test_tenant.id)
        )
    ).scalars().all()

    # What SQL says.
    sql_in_gap = set(
        (
            await db_session.execute(
                select(Environment.id).where(
                    Environment.tenant_id == test_tenant.id,
                    svc.noncompliance_clause(policy),
                )
            )
        ).scalars().all()
    )
    # What the message builder says.
    gaps = svc.gaps_for_environments(envs, policy)
    mirror_in_gap = {env_id for env_id, msgs in gaps.items() if msgs}

    assert sql_in_gap == mirror_in_gap, (
        "the SQL clause and the message mirror disagree about which "
        "environments are in gap"
    )
```

When Task 7 lands, extend this test with the preview's count over the same fixture — `preview_policy` with overrides equal to the saved policy must report `in_gap == len(sql_in_gap)`. Task 7's brief repeats this instruction.

- [ ] **Step 7: Run on both engines**

```bash
cd backend
uv run pytest tests/services/test_environment_compliance_filters.py -v
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/services/test_environment_compliance_filters.py -v
```

Expected: PASS, 10 tests on each.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/environment_compliance_service.py backend/app/services/environment_service.py backend/app/api/v1/schemas/environment.py backend/app/api/v1/environments.py backend/tests/services/test_environment_compliance_filters.py
git commit -m "feat(b2): compliance_gap and quarantined filters, in SQL, with their messages"
```

---

### Task 7: The advisory guard, and the preview endpoint

Two deliverables, one task: they are the sub-project's promise and the tool that makes it safe to enable.

**Files:**
- Modify: `backend/app/api/v1/tenant_admin_fields.py`
- Modify: `backend/app/services/environment_compliance_service.py`
- Modify: `backend/app/api/v1/schemas/environment_naming_policy.py`
- Test: `backend/tests/test_b2_advises_never_blocks.py`
- Test: `backend/tests/test_environment_naming_policy_preview.py`

**Interfaces:**
- Consumes: everything from Tasks 3–6.
- Produces: `POST /api/v1/tenant/environment-naming-policy/preview`, `preview_policy(...) -> PolicyPreview`.

- [ ] **Step 1: Write the guard test — the one that protects the whole design**

```python
# backend/tests/test_b2_advises_never_blocks.py
"""THE guard on B2's design, descended from A1's
`test_an_agreement_changes_no_booking_behaviour` and A4's
`test_a_contention_changes_no_booking_behaviour`.

If this fails, B2 has started acting.
"""
import pytest

from tests.factories import post_environment

POLICY_URL = "/api/v1/tenant/environment-naming-policy"


@pytest.mark.asyncio
async def test_a_quarantined_environment_can_still_be_booked(
    client, auth_headers, db_session, test_tenant, test_booking_type
):
    from datetime import datetime, timedelta, timezone
    from app.services import environment_compliance_service as svc

    created = await post_environment(client, auth_headers, "Legacy Box")
    env_id = created.json()["id"]
    await client.put(
        POLICY_URL,
        json={
            "is_enabled": True,
            "name_pattern": r"[a-z]+-\d{2}",
            "name_pattern_example": "payments-01",
            "required_attributes": [],
            "grace_days": 0,
        },
        headers=auth_headers,
    )
    policy = await svc.load_policy(db_session, test_tenant.id)
    policy.effective_from = datetime.now(timezone.utc) - timedelta(days=30)
    await db_session.flush()

    listed = (
        await client.get(
            "/api/v1/environments/", params={"quarantined": "true"}, headers=auth_headers
        )
    ).json()
    assert [e["name"] for e in listed] == ["Legacy Box"], "precondition: it is quarantined"

    start = datetime.now(timezone.utc) + timedelta(days=1)
    booking = await client.post(
        "/api/v1/booking-requests/",
        json={
            "purpose": "B2 must not block this",
            "booking_type_id": test_booking_type.id,
            "environment_ids": [env_id],
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=1)).isoformat(),
        },
        headers=auth_headers,
    )
    assert booking.status_code in (200, 201), booking.text
```

Read `backend/tests/test_booking_requests_api.py` for the exact create payload this codebase expects and match it — the point of the test is the assertion, not the shape of the request.

- [ ] **Step 2: Run it — it must PASS immediately**

Run: `cd backend && uv run pytest tests/test_b2_advises_never_blocks.py -v`
Expected: PASS. This test is a **regression guard**, not a TDD driver: nothing in Tasks 1–6 touches the booking path, so a failure here means something already overstepped.

- [ ] **Step 3: Prove the guard is not vacuous**

Temporarily add a refusal to `booking_service.create_request` — e.g. raise `HTTPException(422)` when the environment's `name_compliant is False` — and re-run the test. It **must fail**. Then revert the mutation.

A1's equivalent test was proved this way for exactly this reason: a guard that would pass even if the thing it guards were broken guards nothing. Record in the commit message that the check was done.

- [ ] **Step 3b: Extend the three-way agreement test with the preview**

Task 6 Step 6b left this to you. In `backend/tests/services/test_environment_compliance_filters.py`, extend `test_the_sql_clause_and_the_python_mirror_agree_row_for_row` so the preview is the third voice: call `preview_policy` with overrides equal to the saved policy over the same fixture, and assert `in_gap == len(sql_in_gap)`. Three evaluations of one rule, one test that fails when any pair drifts.

- [ ] **Step 4: Write the preview test**

```python
# backend/tests/test_environment_naming_policy_preview.py
import pytest

from tests.factories import post_environment

PREVIEW_URL = "/api/v1/tenant/environment-naming-policy/preview"


@pytest.mark.asyncio
async def test_preview_answers_who_this_would_hit_before_saving(client, auth_headers):
    await post_environment(client, auth_headers, "payments-uat-01")
    await post_environment(client, auth_headers, "Legacy Box")
    await post_environment(client, auth_headers, "Another Old One")

    r = await client.post(
        PREVIEW_URL,
        json={"name_pattern": r"[a-z]+-(dev|uat|prod)-\d{2}", "required_attributes": []},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_environments"] == 3
    assert body["in_gap"] == 2
    assert body["quarantined_now"] == 0, "a brand-new rule quarantines nothing"
    assert sorted(body["sample_names"]) == ["Another Old One", "Legacy Box"]


@pytest.mark.asyncio
async def test_preview_with_no_overrides_describes_the_policy_in_force(
    client, auth_headers
):
    await post_environment(client, auth_headers, "Legacy Box")
    await client.put(
        "/api/v1/tenant/environment-naming-policy",
        json={
            "is_enabled": True,
            "name_pattern": r"[a-z]+-\d{2}",
            "name_pattern_example": "payments-01",
            "required_attributes": [],
            "grace_days": 14,
        },
        headers=auth_headers,
    )
    r = await client.post(PREVIEW_URL, json={}, headers=auth_headers)
    assert r.json()["in_gap"] == 1


@pytest.mark.asyncio
async def test_preview_runs_the_same_redos_guard_as_the_save_path(
    client, auth_headers
):
    r = await client.post(
        PREVIEW_URL, json={"name_pattern": r"(a+)+$"}, headers=auth_headers
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_preview_is_admin_only(client, auth_headers, db_session, test_tenant):
    from tests.factories import ensure_user

    viewer = await ensure_user(db_session, test_tenant.id, role="Viewer")
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": viewer.username, "password": "testpass123", "tenant_slug": test_tenant.slug},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    r = await client.post(PREVIEW_URL, json={}, headers=headers)
    assert r.status_code == 403
```

- [ ] **Step 5: Run and watch the preview tests fail**

Run: `cd backend && uv run pytest tests/test_environment_naming_policy_preview.py -v`
Expected: FAIL — 404, the route does not exist.

- [ ] **Step 6: Implement the preview**

Add the schemas to `backend/app/api/v1/schemas/environment_naming_policy.py`:

```python
class EnvironmentNamingPolicyPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_pattern: Optional[str] = Field(default=None, max_length=500)
    required_attributes: Optional[list[str]] = None


class EnvironmentNamingPolicyPreview(BaseModel):
    total_environments: int
    in_gap: int
    quarantined_now: int
    sample_names: list[str]
```

Add the service function:

```python
_PREVIEW_SAMPLE_LIMIT = 20


async def preview_policy(
    db: AsyncSession,
    tenant_id: int,
    *,
    name_pattern: Optional[str],
    required_attributes: Optional[list[str]],
) -> tuple[int, int, int, list[str]]:
    """Answer 'who does this hit?' for a policy that may not be saved yet.

    The candidate pattern is evaluated HERE, in Python, against the tenant's
    live names — never in the browser. A JavaScript regex engine would be a
    fourth opinion on a rule this design deliberately gives one owner.
    """
    stored = await load_policy(db, tenant_id)
    candidate = EnvironmentNamingPolicy(
        tenant_id=tenant_id,
        is_enabled=True,
        name_pattern=(
            name_pattern if name_pattern is not None
            else (stored.name_pattern if stored else None)
        ),
        name_pattern_example=stored.name_pattern_example if stored else None,
        required_attributes=(
            required_attributes if required_attributes is not None
            else (list(stored.required_attributes) if stored else [])
        ),
        grace_days=stored.grace_days if stored else 14,
        effective_from=stored.effective_from if stored else datetime.now(timezone.utc),
    )
    await validate_pattern_async(candidate.name_pattern, None)
    await _assert_attributes_known(db, tenant_id, candidate.required_attributes)

    envs = (
        await db.execute(
            select(Environment).where(
                Environment.tenant_id == tenant_id,
                Environment.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    cutoff = expiry_boundary(now) - timedelta(days=candidate.grace_days)
    grace_elapsed = candidate.effective_from <= cutoff

    in_gap, quarantined, sample = 0, 0, []
    for env in envs:
        # The candidate's verdict, computed here — the STORED verdict belongs
        # to the saved policy and must not be consulted for a hypothetical one.
        name_bad = (
            candidate.name_pattern is not None
            and not name_matches(candidate.name_pattern, env.name)
        )
        attrs_bad = any(
            _is_attribute_missing(env, a)
            if a in _ATTRIBUTE_LABELS
            else (
                a.startswith(CUSTOM_FIELD_PREFIX)
                and str((env.custom_fields or {}).get(a[len(CUSTOM_FIELD_PREFIX):]) or "").strip() == ""
            )
            for a in candidate.required_attributes
        )
        if name_bad or attrs_bad:
            in_gap += 1
            if len(sample) < _PREVIEW_SAMPLE_LIMIT:
                sample.append(env.name)
            if grace_elapsed and env.created_at <= cutoff:
                quarantined += 1
    return len(envs), in_gap, quarantined, sample
```

Add the endpoint to `backend/app/api/v1/tenant_admin_fields.py`:

```python
@router.post(
    "/environment-naming-policy/preview",
    response_model=EnvironmentNamingPolicyPreview,
)
async def preview_environment_naming_policy(
    data: EnvironmentNamingPolicyPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    """What a policy would do, before it does it.

    Unbounded by design, like the other rollup endpoints — it counts the whole
    estate, which is the question being asked. Listed as such in
    docs/pagination.md.
    """
    total, in_gap, quarantined, sample = (
        await environment_compliance_service.preview_policy(
            db,
            current_user.active_tenant_id,
            name_pattern=data.name_pattern,
            required_attributes=data.required_attributes,
        )
    )
    return EnvironmentNamingPolicyPreview(
        total_environments=total,
        in_gap=in_gap,
        quarantined_now=quarantined,
        sample_names=sample,
    )
```

- [ ] **Step 7: Run both test files on both engines**

```bash
cd backend
uv run pytest tests/test_b2_advises_never_blocks.py tests/test_environment_naming_policy_preview.py -v
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test \
  uv run pytest tests/test_b2_advises_never_blocks.py tests/test_environment_naming_policy_preview.py -v
```

Expected: PASS on both.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/v1/schemas/environment_naming_policy.py backend/app/services/environment_compliance_service.py backend/app/api/v1/tenant_admin_fields.py backend/tests/test_b2_advises_never_blocks.py backend/tests/test_environment_naming_policy_preview.py
git commit -m "feat(b2): policy preview, and the guard that B2 never blocks a booking

The advisory guard was proved non-vacuous by inserting a real refusal into
booking_service.create_request and watching it fail."
```

---

### Task 8: Frontend — policy types, service, slice and admin panel

**Files:**
- Create: `frontend/src/services/environmentNamingPolicyService.ts`
- Create: `frontend/src/store/environmentNamingPolicySlice.ts`
- Create: `frontend/src/components/admin/EnvironmentNamingPolicyPanel.tsx`
- Create: `frontend/src/components/admin/__tests__/environmentNamingPolicyPanel.test.tsx`
- Modify: `frontend/src/types/environment.ts`
- Modify: `frontend/src/store/index.ts` (register the reducer)
- Modify: `frontend/src/pages/admin/EntityConfig.tsx` (mount the panel)

**Interfaces:**
- Consumes: `GET/PUT/POST /tenant/environment-naming-policy[/preview]` (Tasks 4, 7).
- Produces: `EnvironmentNamingPolicy`, `EnvironmentNamingPolicyPreview` types; `environmentNamingPolicyService`; thunks `fetchNamingPolicy`, `saveNamingPolicy`, `previewNamingPolicy`.

- [ ] **Step 1: Write the failing component test**

```tsx
// frontend/src/components/admin/__tests__/environmentNamingPolicyPanel.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '../../../test/renderWithProviders';
import EnvironmentNamingPolicyPanel from '../EnvironmentNamingPolicyPanel';
import { environmentNamingPolicyService } from '../../../services/environmentNamingPolicyService';

vi.mock('../../../services/environmentNamingPolicyService');

const POLICY = {
  is_enabled: true,
  name_pattern: '[a-z]+-(dev|uat|prod)-\\d{2}',
  name_pattern_example: 'payments-uat-01',
  required_attributes: ['owner'],
  grace_days: 14,
  effective_from: '2026-08-09T00:00:00Z',
};

beforeEach(() => {
  vi.mocked(environmentNamingPolicyService.get).mockResolvedValue(POLICY);
  vi.mocked(environmentNamingPolicyService.save).mockResolvedValue(POLICY);
  vi.mocked(environmentNamingPolicyService.preview).mockResolvedValue({
    total_environments: 12,
    in_gap: 9,
    quarantined_now: 0,
    sample_names: ['Legacy Box'],
  });
});

describe('EnvironmentNamingPolicyPanel', () => {
  it('loads the policy in force', async () => {
    renderWithProviders(<EnvironmentNamingPolicyPanel />);
    expect(await screen.findByDisplayValue('payments-uat-01')).toBeInTheDocument();
  });

  it('previews who a rule would hit before it is saved', async () => {
    renderWithProviders(<EnvironmentNamingPolicyPanel />);
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));
    expect(await screen.findByText(/9 of 12/i)).toBeInTheDocument();
    expect(screen.getByText(/none quarantined/i)).toBeInTheDocument();
  });

  it('shows the server error text, not an HTTP status', async () => {
    // RTK's default serializer copies only name/message/stack/code, so a real
    // AxiosError's .message is "Request failed with status code 422" and the
    // server's response.data.detail is dropped. Mocking a plain Error carrying
    // the final text would pass while the app is broken — so mock the Axios
    // shape.
    const axiosError = Object.assign(new Error('Request failed with status code 422'), {
      isAxiosError: true,
      response: { status: 422, data: { detail: 'That pattern is too slow to evaluate safely' } },
    });
    vi.mocked(environmentNamingPolicyService.save).mockRejectedValue(axiosError);

    renderWithProviders(<EnvironmentNamingPolicyPanel />);
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText(/too slow to evaluate safely/i)).toBeInTheDocument()
    );
    expect(screen.queryByText(/status code 422/i)).not.toBeInTheDocument();
  });

  it('never evaluates the pattern in the browser', async () => {
    // A JS regex engine would be a fourth opinion on a rule this design gives
    // one owner. The test box goes through the server.
    const spy = vi.spyOn(RegExp.prototype, 'test');
    renderWithProviders(<EnvironmentNamingPolicyPanel />);
    await screen.findByDisplayValue('payments-uat-01');
    await userEvent.click(screen.getByRole('button', { name: /preview/i }));
    await screen.findByText(/9 of 12/i);
    expect(environmentNamingPolicyService.preview).toHaveBeenCalled();
    spy.mockRestore();
  });
});
```

Check `frontend/src/test/` for the real `renderWithProviders` helper (or the pattern the other admin-panel tests use, in `frontend/src/components/admin/__tests__/environmentTiersPanel.test.tsx`) and match it.

- [ ] **Step 2: Run it and watch it fail**

Run: `cd frontend && npx vitest run src/components/admin/__tests__/environmentNamingPolicyPanel.test.tsx`
Expected: FAIL — cannot resolve `../EnvironmentNamingPolicyPanel`.

- [ ] **Step 3: Add the types**

Append to `frontend/src/types/environment.ts`:

```ts
export interface EnvironmentNamingPolicy {
  is_enabled: boolean;
  name_pattern: string | null;
  name_pattern_example: string | null;
  required_attributes: string[];
  grace_days: number;
  effective_from: string;
}

export interface EnvironmentNamingPolicyPreview {
  total_environments: number;
  in_gap: number;
  quarantined_now: number;
  sample_names: string[];
}
```

and add to the existing `EnvironmentResponse` interface:

```ts
  /** NULL means no pattern applies — it counts as compliant, never as failing. */
  name_compliant?: boolean | null;
  quarantined?: boolean;
  compliance_gaps?: string[];
```

- [ ] **Step 4: Write the service**

```ts
// frontend/src/services/environmentNamingPolicyService.ts
import api from './api';
import type {
  EnvironmentNamingPolicy,
  EnvironmentNamingPolicyPreview,
} from '../types/environment';

const BASE = '/tenant/environment-naming-policy';

export const environmentNamingPolicyService = {
  get: (): Promise<EnvironmentNamingPolicy> => api.get(BASE).then((r) => r.data),

  save: (data: EnvironmentNamingPolicy): Promise<EnvironmentNamingPolicy> =>
    api.put(BASE, data).then((r) => r.data),

  preview: (data: {
    name_pattern?: string | null;
    required_attributes?: string[];
  }): Promise<EnvironmentNamingPolicyPreview> =>
    api.post(`${BASE}/preview`, data).then((r) => r.data),
};
```

- [ ] **Step 5: Write the slice**

```ts
// frontend/src/store/environmentNamingPolicySlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';

import { environmentNamingPolicyService } from '../services/environmentNamingPolicyService';
import { formatApiError } from '../services/apiError';
import type {
  EnvironmentNamingPolicy,
  EnvironmentNamingPolicyPreview,
} from '../types/environment';

interface State {
  policy: EnvironmentNamingPolicy | null;
  preview: EnvironmentNamingPolicyPreview | null;
  loading: boolean;
  error: string | null;
}

const initialState: State = { policy: null, preview: null, loading: false, error: null };

export const fetchNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/fetch',
  async (_, { rejectWithValue }) => {
    try {
      return await environmentNamingPolicyService.get();
    } catch (err) {
      return rejectWithValue(formatApiError(err));
    }
  }
);

export const saveNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/save',
  async (data: EnvironmentNamingPolicy, { rejectWithValue }) => {
    try {
      return await environmentNamingPolicyService.save(data);
    } catch (err) {
      // rejectWithValue(formatApiError(err)) and NOT the default serializer:
      // miniSerializeError copies only name/message/stack/code, so the
      // server's response.data.detail — the actual reason — is dropped.
      return rejectWithValue(formatApiError(err));
    }
  }
);

export const previewNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/preview',
  async (
    data: { name_pattern?: string | null; required_attributes?: string[] },
    { rejectWithValue }
  ) => {
    try {
      return await environmentNamingPolicyService.preview(data);
    } catch (err) {
      return rejectWithValue(formatApiError(err));
    }
  }
);

const slice = createSlice({
  name: 'environmentNamingPolicy',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchNamingPolicy.pending, (s) => {
        s.loading = true;
        s.error = null;
        // Cleared on pending, not only on fulfilled: a panel that outlives an
        // unmount would otherwise render the previous tenant's policy under
        // the new one's heading.
        s.policy = null;
      })
      .addCase(fetchNamingPolicy.fulfilled, (s, a) => {
        s.loading = false;
        s.policy = a.payload;
      })
      .addCase(fetchNamingPolicy.rejected, (s, a) => {
        s.loading = false;
        s.error = a.payload as string;
      })
      .addCase(saveNamingPolicy.fulfilled, (s, a) => {
        s.policy = a.payload;
        s.error = null;
      })
      .addCase(saveNamingPolicy.rejected, (s, a) => {
        s.error = a.payload as string;
      })
      .addCase(previewNamingPolicy.pending, (s) => {
        s.preview = null;
      })
      .addCase(previewNamingPolicy.fulfilled, (s, a) => {
        s.preview = a.payload;
      })
      .addCase(previewNamingPolicy.rejected, (s, a) => {
        s.error = a.payload as string;
      });
  },
});

export default slice.reducer;
```

Register it in `frontend/src/store/index.ts` as `environmentNamingPolicy: environmentNamingPolicyReducer`.

- [ ] **Step 6: Write the panel**

Model it on `frontend/src/components/admin/EnvironmentTiersPanel.tsx` for layout, MUI imports and the surrounding `EntityConfig` conventions. It must contain:

- a `Switch` bound to `is_enabled`;
- `TextField`s for `name_pattern`, `name_pattern_example` and `grace_days` (`type="number"`, `inputProps={{ min: 0 }}`);
- a `Select` (`multiple`) for `required_attributes`, whose options are `owner`, `expiry`, `operations_group` plus `cf:<field_key>` for each environment custom field fetched from `GET /tenant/fields?entity_type=environment`;
- a **Preview** button dispatching `previewNamingPolicy` with the *current form values* (not the saved ones), rendering `"{in_gap} of {total_environments} environments would be in gap"` and either `"none quarantined yet"` or the count;
- a **Save** button dispatching `saveNamingPolicy`, reading `result.payload` on rejection and rendering it in an `<Alert severity="error">`;
- helper text under `required_attributes` stating in as many words: *"This affects reporting only. To refuse a save outright, mark the custom field required in Custom Fields."*
- helper text under the whole panel: *"Existing environments are never frozen: a save that keeps a non-conforming name unchanged is accepted, and nothing quarantines until the grace period elapses."*

- [ ] **Step 7: Mount it and run the tests**

Add the panel to `frontend/src/pages/admin/EntityConfig.tsx` beside `EnvironmentTiersPanel`.

```bash
cd frontend
npx vitest run src/components/admin/__tests__/environmentNamingPolicyPanel.test.tsx
npm run lint
npm run build
```

Expected: 4 tests PASS; lint and build clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/services/environmentNamingPolicyService.ts frontend/src/store/environmentNamingPolicySlice.ts frontend/src/store/index.ts frontend/src/components/admin/EnvironmentNamingPolicyPanel.tsx frontend/src/components/admin/__tests__/environmentNamingPolicyPanel.test.tsx frontend/src/types/environment.ts frontend/src/pages/admin/EntityConfig.tsx
git commit -m "feat(b2): admin panel for the environment naming policy, with server-side preview"
```

---

### Task 9: Frontend — the grid column, the filter chips, and the detail banner

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentList.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`
- Modify: `frontend/src/services/environmentService.ts` (two new params)
- Create: `frontend/src/pages/environments/__tests__/environmentCompliance.test.tsx`

**Interfaces:**
- Consumes: `EnvironmentResponse.name_compliant | quarantined | compliance_gaps` (Task 6).
- Produces: no exports; UI only.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/pages/environments/__tests__/environmentCompliance.test.tsx
import { describe, it, expect } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { renderWithProviders } from '../../../test/renderWithProviders';
import EnvironmentList from '../EnvironmentList';

describe('B2 advises; it never blocks', () => {
  it('renders no control that would prevent booking a quarantined environment', async () => {
    // The fixture is deliberately one where a block COULD be observed: the row
    // is quarantined AND the page renders its actions. A3's reviewer gated a
    // control on a gap and watched 50 tests pass because the fixture could not
    // have shown the control either way.
    renderWithProviders(<EnvironmentList />, {
      preloadedState: {
        environments: {
          environments: [
            {
              id: 1,
              name: 'Legacy Box',
              tier_id: 1,
              tier_name: 'Dev',
              status: 'active',
              tenant_id: 1,
              reserved_now: false,
              name_compliant: false,
              quarantined: true,
              compliance_gaps: ['The name does not match this tenant\'s naming convention'],
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
          total: 1,
          loading: false,
          error: null,
        },
      },
    });
    expect(await screen.findByText('Legacy Box')).toBeInTheDocument();
    expect(screen.queryByText(/cannot be booked/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/blocked/i)).not.toBeInTheDocument();
  });
});

describe('EnvironmentList compliance filters', () => {
  it("spells no-selection as an omitted key, never 'all'", async () => {
    // buildParams' own sentinel is 'all', so a vocabulary containing it builds
    // byte-identical params for two different states and the grid never
    // refetches.
    renderWithProviders(<EnvironmentList />);
    const chip = await screen.findByText(/quarantined/i);
    await userEvent.click(chip);
    await userEvent.click(chip);
    // Two clicks return to no-selection: the param must be absent, not 'all'.
    expect(window.location.search).not.toContain('all');
  });
});
```

Read `frontend/src/pages/environments/__tests__/` for the existing list-page test setup and match its store shape — the preloaded slice keys above are illustrative of intent, not of this codebase's exact names.

- [ ] **Step 2: Run and watch it fail**

Run: `cd frontend && npx vitest run src/pages/environments/__tests__/environmentCompliance.test.tsx`
Expected: FAIL — no "Quarantined" chip exists.

- [ ] **Step 3: Extend the service params**

In `frontend/src/services/environmentService.ts`, add to `listEnvironments`' params type:

```ts
    compliance_gap?: boolean;
    quarantined?: boolean;
```

- [ ] **Step 4: Add the filter keys and the chips**

In `frontend/src/pages/environments/EnvironmentList.tsx`, add `'compliance_gap'` and `'quarantined'` to the `useServerGrid` `filterKeys` array, then add two chips beside the existing "Governance gap" chip, following its exact shape:

```tsx
        <Chip
          // The tenant's own naming/tagging policy, as opposed to
          // `governance_gap`, which is B1's fixed pair (owner + operating
          // team). Overlapping by design; see docs/admin-guide.md.
          label="Policy gap"
          clickable
          color={grid.filters.compliance_gap === 'true' ? 'warning' : 'default'}
          variant={grid.filters.compliance_gap === 'true' ? 'filled' : 'outlined'}
          onClick={() =>
            grid.setFilter(
              'compliance_gap',
              grid.filters.compliance_gap === 'true' ? '' : 'true'
            )
          }
        />
        <Chip
          // Advisory: a quarantined environment can still be booked.
          label="Quarantined"
          clickable
          color={grid.filters.quarantined === 'true' ? 'error' : 'default'}
          variant={grid.filters.quarantined === 'true' ? 'filled' : 'outlined'}
          onClick={() =>
            grid.setFilter('quarantined', grid.filters.quarantined === 'true' ? '' : 'true')
          }
        />
```

`''` is the no-selection value — **not** `'all'`, which `buildParams` treats as its own sentinel.

- [ ] **Step 5: Add the grid column**

Add to the `columns` array, following the `reserved_now` column's shape:

```tsx
    {
      field: 'compliance',
      headerName: 'Compliance',
      width: 150,
      // Computed from name_compliant + created_at + the policy, so there is no
      // single column to order by — docs/pagination.md's unsortable set.
      sortable: false,
      renderCell: (params) => {
        if (params.row.quarantined) {
          return <Chip label="Quarantined" size="small" color="error" />;
        }
        if ((params.row.compliance_gaps ?? []).length > 0) {
          return (
            <Tooltip title={params.row.compliance_gaps.join('; ')}>
              <Chip label="Policy gap" size="small" color="warning" />
            </Tooltip>
          );
        }
        return '—';
      },
    },
```

The field id is `compliance`, not a bare custom-field-style key. Environment custom-field columns are already namespaced `cf_<key>`, so this cannot collide — but check `buildCustomFieldColumns` in this file before committing: a static column sharing an id with a custom field makes MUI emit a visibility change that `saveColumnModel` then persists, silently hiding the real column, and no fixture defines a colliding custom field so no test would catch it.

- [ ] **Step 6: Add the detail banner and the name helper text**

In `EnvironmentDetail.tsx`, beside the existing governance panel, render an `<Alert severity={quarantined ? 'error' : 'warning'}>` when `compliance_gaps.length > 0`, listing each gap and — for a quarantined environment — saying plainly that it remains bookable and what to fix. Add the pattern and its example as `helperText` under the name field in the create and edit forms, fetched from the policy endpoint (which any tenant member may read).

- [ ] **Step 7: Run the tests, lint and build**

```bash
cd frontend
npx vitest run src/pages/environments
npm run lint
npm run build
```

Expected: PASS, clean.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/environments frontend/src/services/environmentService.ts
git commit -m "feat(b2): compliance column, policy-gap and quarantined chips, detail banner"
```

---

### Task 10: Documentation

**Files:**
- Modify: `docs/pagination.md`
- Modify: `docs/admin-guide.md`
- Modify: `docs/user-guide.md`
- Modify: `docs/phases/phase-7.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: `docs/pagination.md`**

Add `quarantined` to the permanently-unsortable list as its **fourteenth** member, with the one-line reason ("computed from `name_compliant` + `created_at` + the policy; no single column backs it"). Add `POST /tenant/environment-naming-policy/preview` to the deliberately-unbounded set. Note that `GET /environments` gained two SQL filters that run before the window, so `X-Total-Count` still describes the filtered set.

- [ ] **Step 2: `docs/admin-guide.md`**

A new section covering: how to write a pattern and why the example matters; that reads are open to all members and writes are Admin; that **enabling a policy will show most of the estate as non-compliant on day one**, which is expected and is what the grace period is for; that the preview tells you the number before you enable; the difference between "Governance gap" (B1's fixed pair) and "Policy gap" (this policy); and that marking a custom field `required` refuses a save while listing it here only reports.

- [ ] **Step 3: `docs/user-guide.md`**

A short section: what "Policy gap" and "Quarantined" mean on the Environments list; that **quarantine changes nothing you can do** — the environment can still be booked and used; and how to clear it.

- [ ] **Step 4: `docs/phases/phase-7.md`**

Tick B2, link the spec, and add a "What B2 established" section in the shape of the A1–A4 and B1–B3b sections above it. It must record: B2 advises and never blocks (naming the guard test); the stored verdict and its four-item invalidation surface; null-means-compliant; the `governance_gap` overlap and why it was left; the tier exclusion; the day-granular grace clock; and the ReDoS residual risk.

- [ ] **Step 5: `CLAUDE.md`**

Add a B2 block in the established style, and add one new entry to **Common Pitfalls**:

> - **Evaluating a tenant's regex anywhere but `environment_compliance_service.name_matches`** — the name verdict is stored precisely because no regex is portable across both engines. A second evaluator (PostgreSQL's `~`, a SQLite callback, or a JavaScript `RegExp` in an admin form) is a second opinion on one rule, and the two disagree on real patterns: a name refused at save then reports compliant in the list. The scratch "test a name" box goes through the server for this reason.

- [ ] **Step 6: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs(b2): naming policy in the admin/user guides, phase-7 and the pitfalls"
```

---

### Task 11: Whole-branch verification

Nothing here is optional. Six defects across the pagination programme were found only by opening the page with a fully green suite.

- [ ] **Step 1: Full suite, both engines**

```bash
cd backend
uv run pytest -q
TEST_DATABASE_URL=postgresql+asyncpg://envmgr:envmgr_dev_password@localhost:5432/envmgr_test uv run pytest -q
cd ../frontend && npx vitest run && npm run lint && npm run build
```

Expected: all green. Paste the actual counts into the final report — not "tests pass".

- [ ] **Step 2: Mutation-test the rules that matter**

For each, make the change, confirm a **named** test fails, then revert:

1. Delete the `submitted == stored` carve-out in `assert_name_allowed` → `test_a_full_form_save_with_an_unchanged_bad_name_is_accepted` fails.
2. Change `Environment.name_compliant.is_(False)` to `.is_not(True)` in `noncompliance_clause` → `test_a_null_verdict_counts_as_compliant_under_a_live_policy` fails.
3. Replace `expiry_boundary(now)` with `now` in `quarantine_clause` → `test_a_deadline_is_a_day` fails.
4. Remove the `evaluate_name` call from `update_environment` → `test_a_rename_re_evaluates` fails.
5. Bump `effective_from` unconditionally in `upsert_policy` → the `grace_days` half of the effective-from test fails.

Any mutation that survives means the rule is documented but unguarded — the exact shape that produced six of seven survivors on A4. Write the test.

- [ ] **Step 3: Browser pass**

Run the app (`docker-compose up -d`, then backend and frontend per CLAUDE.md), log in as `admin`/`admin123` in tenant `demo`, and walk it:

1. Admin → Entity Config → save a policy matching **some** existing environments. Confirm the preview count matches what the grid then shows.
2. Environments list: the Compliance column renders (jsdom could not render A3's equivalent column at all, so this is the first time anyone sees it), both chips filter, and the total in the footer changes with them.
3. Rename a conforming environment to a non-conforming name → the 422 reaches the UI **with the pattern and example in the message**, not "Request failed with status code 422".
4. Save an unrelated field on a non-conforming environment → accepted.
5. Set `grace_days` to 0, reload → environments appear as Quarantined; **book one** and confirm it works.
6. Environment detail: the banner lists the gaps.

- [ ] **Step 4: Report honestly**

State test counts for both engines, which mutations were tried and what failed, and what the browser pass showed — including anything that did not work. If a step was skipped, say so.

- [ ] **Step 5: Final commit and branch handoff**

```bash
git add -A
git commit -m "test(b2): whole-branch verification — dual engine, mutation pass, browser pass"
```

Then use the **superpowers:finishing-a-development-branch** skill to decide how this integrates.

---

## Self-Review

**Spec coverage:** policy model → Task 2; regex evaluator + ReDoS → Task 3; the four-part invalidation surface → Task 5; fulfilment-never-422s → Task 5; two verdicts + SQL filters + response fields → Task 6; `cf:` portability spike → Task 1 (first, as the spec demands); preview + advisory guard → Task 7; admin panel and server-side test box → Task 8; grid column, chips, banner, helper text → Task 9; docs including the unsortable list and the first-deploy optics → Task 10; dual engine, mutation, browser → Task 11.

**Known gaps, deliberately left to the implementer:** three snippets depend on code the plan could not quote verbatim — `ensure_environment_request`'s signature and the approve/fulfil call in Task 5 Step 6, the booking-create payload in Task 7 Step 1, and the list-page store shape in Task 9 Step 1. Each says to read the real code and match it. The `EnvironmentDetail` banner and the name-field helper text (Task 9 Step 6) are specified by behaviour rather than by code, because that file was not read while planning.
