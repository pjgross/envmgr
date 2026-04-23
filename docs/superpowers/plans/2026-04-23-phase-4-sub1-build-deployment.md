# Phase 4 Sub-1 — Build + Deployment Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a custom-JSON CI/CD webhook that creates Build + Deployment rows, auto-links them to a `code_deployment` change request, and updates the environment-subsystem-version audit trail — all authenticated by tenant-scoped API keys, with per-tenant custom fields supported at both Build and Deployment level.

**Architecture:** One alembic revision creates `api_key`, `build`, `deployment` + renames `environment_subsystem_version.build_id` to `build_identifier` + adds a new `build_fk_id` FK column. A `DeploymentService.ingest` method handles the whole webhook flow in one transaction: slug resolution → build upsert → CR resolution (payload or auto-created via a seeded minimal `code_deployment` lifecycle) → deployment insert → status-driven side effects → outbox event. Auth for the webhook uses a new `api_key_auth` FastAPI dependency; JWT endpoints are untouched.

**Tech Stack:** FastAPI, SQLAlchemy (async), Alembic, Pydantic v2, Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-04-23-phase-4-sub1-build-deployment-design.md`

**Working directory (already set up by brainstorming):** Feature branch `feature/phase-4-sub1-build-deployment` off `main` tip `a58d071`. Run all commands from the repo root unless otherwise stated.

---

## Task 1: `ApiKey` model + schema

**Files:**
- Create: `backend/app/db/models/api_key.py`
- Modify: `backend/app/db/models/__init__.py` — add `from app.db.models.api_key import ApiKey`
- Create: `backend/app/api/v1/schemas/api_key.py`

- [ ] **Step 1: Write the failing model-import test**

Create `backend/tests/test_api_key_model.py`:

```python
"""Smoke test for the ApiKey model — shape + column nullability."""
from app.db.models.api_key import ApiKey


def test_api_key_model_columns():
    cols = {c.name: c for c in ApiKey.__table__.columns}
    assert "key_hash" in cols
    assert cols["key_hash"].nullable is False
    assert "name" in cols
    assert cols["scopes"].nullable is False
    assert cols["created_by"].nullable is False
    assert cols["last_used_at"].nullable is True
    assert cols["expires_at"].nullable is True
    assert cols["tenant_id"].nullable is False
    assert cols["deleted_at"].nullable is True
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/test_api_key_model.py -v
```

Expected: `ModuleNotFoundError: app.db.models.api_key`.

- [ ] **Step 3: Create the model**

`backend/app/db/models/api_key.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ApiKey(Base):
    __tablename__ = "api_key"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_hash", name="uq_api_key_tenant_hash"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"), nullable=False, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Register the model for `create_all`**

In `backend/app/db/models/__init__.py`, in alphabetical order with siblings:

```python
from app.db.models.api_key import ApiKey
```

And add `"ApiKey"` to `__all__` list.

- [ ] **Step 5: Create Pydantic schemas**

`backend/app/api/v1/schemas/api_key.py`:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(..., max_length=120)
    scopes: list[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    scopes: list[str]
    created_by: int
    created_by_username: Optional[str] = None
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime


class ApiKeyCreated(ApiKeyRead):
    """Returned exactly once from POST — includes the raw key."""
    raw_key: str
```

- [ ] **Step 6: Run — confirm pass**

```bash
cd backend && uv run pytest tests/test_api_key_model.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/api_key.py backend/app/db/models/__init__.py backend/app/api/v1/schemas/api_key.py backend/tests/test_api_key_model.py
git commit -m "feat(phase-4): add ApiKey model + schemas"
```

---

## Task 2: `Build` model + schema

**Files:**
- Create: `backend/app/db/models/build.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/app/api/v1/schemas/build.py`

- [ ] **Step 1: Write the failing model-import test**

Create `backend/tests/test_build_model.py`:

```python
"""Smoke test for the Build model — required columns + nullability."""
from app.db.models.build import Build


def test_build_model_columns():
    cols = {c.name: c for c in Build.__table__.columns}
    for required in ("subsystem_id", "git_sha", "commit_timestamp", "tenant_id"):
        assert required in cols, required
        assert cols[required].nullable is False, required
    for optional in ("release_id", "git_branch", "build_number",
                     "build_started_at", "build_finished_at"):
        assert cols[optional].nullable is True, optional
    for jsonish in ("jira_tickets", "pipeline_steps", "custom_fields"):
        assert jsonish in cols, jsonish
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/test_build_model.py -v
```

Expected: `ModuleNotFoundError: app.db.models.build`.

- [ ] **Step 3: Create the model**

`backend/app/db/models/build.py`:

```python
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Build(Base):
    __tablename__ = "build"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "subsystem_id", "git_sha", "build_number",
            name="uq_build_tenant_sub_sha_num",
        ),
        Index("ix_build_tenant_subsystem", "tenant_id", "subsystem_id"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    git_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    git_branch: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    build_number: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    commit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    build_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    build_finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    jira_tickets: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    pipeline_steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    custom_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Register model**

In `backend/app/db/models/__init__.py`:

```python
from app.db.models.build import Build
```

Add `"Build"` to `__all__`.

- [ ] **Step 5: Create schemas**

`backend/app/api/v1/schemas/build.py`:

```python
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field


class PipelineStep(BaseModel):
    name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class BuildPayload(BaseModel):
    """Nested block inside the deployment webhook payload."""
    git_sha: str = Field(..., max_length=64)
    git_branch: Optional[str] = Field(None, max_length=255)
    build_number: Optional[str] = Field(None, max_length=80)
    commit_timestamp: datetime
    build_started_at: Optional[datetime] = None
    build_finished_at: Optional[datetime] = None
    jira_tickets: list[str] = Field(default_factory=list)
    pipeline_steps: list[PipelineStep] = Field(default_factory=list)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class BuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    subsystem_id: int
    release_id: Optional[int]
    git_sha: str
    git_branch: Optional[str]
    build_number: Optional[str]
    commit_timestamp: datetime
    build_started_at: Optional[datetime]
    build_finished_at: Optional[datetime]
    jira_tickets: list[str]
    pipeline_steps: list[PipelineStep]
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 6: Run — confirm pass**

```bash
cd backend && uv run pytest tests/test_build_model.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/build.py backend/app/db/models/__init__.py backend/app/api/v1/schemas/build.py backend/tests/test_build_model.py
git commit -m "feat(phase-4): add Build model + schemas"
```

---

## Task 3: `Deployment` model + schema

**Files:**
- Create: `backend/app/db/models/deployment.py`
- Modify: `backend/app/db/models/__init__.py`
- Create: `backend/app/api/v1/schemas/deployment.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_deployment_model.py`:

```python
"""Smoke test for the Deployment model — required + nullable columns."""
from app.db.models.deployment import Deployment


def test_deployment_model_columns():
    cols = {c.name: c for c in Deployment.__table__.columns}
    for required in ("build_id", "environment_id", "change_request_id",
                     "event_id", "deployed_at", "status", "tenant_id"):
        assert required in cols, required
        assert cols[required].nullable is False, required
    for optional in ("release_id", "deployer_name", "completed_at"):
        assert cols[optional].nullable is True, optional
    assert "custom_fields" in cols
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/test_deployment_model.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create the model**

`backend/app/db/models/deployment.py`:

```python
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import String, DateTime, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Deployment(Base):
    __tablename__ = "deployment"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_id", name="uq_deployment_tenant_event"),
    )

    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    build_id: Mapped[int] = mapped_column(
        ForeignKey("build.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    release_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("release.id", ondelete="SET NULL"), nullable=True, index=True
    )
    change_request_id: Mapped[int] = mapped_column(
        ForeignKey("change_request.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    deployer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    custom_fields: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: Register model**

In `backend/app/db/models/__init__.py`:

```python
from app.db.models.deployment import Deployment
```

Add `"Deployment"` to `__all__`.

- [ ] **Step 5: Create schemas**

`backend/app/api/v1/schemas/deployment.py`:

```python
from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.schemas.build import BuildPayload


class DeploymentWebhookPayload(BaseModel):
    """Body of POST /api/v1/webhooks/deployment."""
    event_id: UUID
    system_slug: str
    subsystem_slug: str
    environment_slug: str
    status: str
    deployed_at: datetime
    release_id: Optional[int] = None
    change_request_id: Optional[int] = None
    deployer_name: Optional[str] = None
    build: BuildPayload
    deployment_custom_fields: dict[str, Any] = Field(default_factory=dict)


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    build_id: int
    environment_id: int
    release_id: Optional[int]
    change_request_id: int
    event_id: UUID
    deployer_name: Optional[str]
    deployed_at: datetime
    completed_at: Optional[datetime]
    status: str
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DeploymentIngestResult(BaseModel):
    deployment_id: int
    build_id: int
    change_request_id: int
    replayed: bool


class DeploymentLinkChangeRequest(BaseModel):
    change_request_id: int
```

- [ ] **Step 6: Run — confirm pass**

```bash
cd backend && uv run pytest tests/test_deployment_model.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/models/deployment.py backend/app/db/models/__init__.py backend/app/api/v1/schemas/deployment.py backend/tests/test_deployment_model.py
git commit -m "feat(phase-4): add Deployment model + schemas"
```

---

## Task 4: Alembic migration — tables + ESSV rename + FK column

**Files:**
- Create: `backend/app/db/migrations/versions/20260424_1200_p4s1_build_deployment.py`

- [ ] **Step 1: Find the current head revision**

```bash
ls backend/app/db/migrations/versions/ | sort | tail -2
```

Expected: `20260423_1200_p3s8_gate_due_date.py` is the most recent. Its `revision` is `p3s8gateduedate` — use this as `down_revision`.

- [ ] **Step 2: Write the migration**

Create `backend/app/db/migrations/versions/20260424_1200_p4s1_build_deployment.py`:

```python
"""phase 4 sub-1: api_key + build + deployment tables; ESSV rename + FK

Revision ID: p4s1builddeploy
Revises: p3s8gateduedate
Create Date: 2026-04-24 12:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


revision: str = "p4s1builddeploy"
down_revision: Union[str, None] = "p3s8gateduedate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, table: str) -> bool:
    return table in Inspector.from_engine(conn).get_table_names()


def _column_exists(conn, table: str, column: str) -> bool:
    return any(c["name"] == column for c in Inspector.from_engine(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "api_key"):
        op.create_table(
            "api_key",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("key_hash", sa.String(64), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.UniqueConstraint("tenant_id", "key_hash", name="uq_api_key_tenant_hash"),
        )
        op.create_index("ix_api_key_tenant_id", "api_key", ["tenant_id"])
        op.create_index("ix_api_key_created_by", "api_key", ["created_by"])

    if not _table_exists(conn, "build"):
        op.create_table(
            "build",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("subsystem_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=True),
            sa.Column("git_sha", sa.String(64), nullable=False),
            sa.Column("git_branch", sa.String(255), nullable=True),
            sa.Column("build_number", sa.String(80), nullable=True),
            sa.Column("commit_timestamp", sa.DateTime(timezone=True), nullable=False),
            sa.Column("build_started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("build_finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("jira_tickets", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("pipeline_steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
            sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["subsystem_id"], ["subsystem.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="SET NULL"),
            sa.UniqueConstraint(
                "tenant_id", "subsystem_id", "git_sha", "build_number",
                name="uq_build_tenant_sub_sha_num",
            ),
        )
        op.create_index("ix_build_tenant_id", "build", ["tenant_id"])
        op.create_index("ix_build_subsystem_id", "build", ["subsystem_id"])
        op.create_index("ix_build_release_id", "build", ["release_id"])
        op.create_index("ix_build_tenant_subsystem", "build", ["tenant_id", "subsystem_id"])

    if not _table_exists(conn, "deployment"):
        op.create_table(
            "deployment",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("tenant_id", sa.Integer(), nullable=False),
            sa.Column("build_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("release_id", sa.Integer(), nullable=True),
            sa.Column("change_request_id", sa.Integer(), nullable=False),
            sa.Column("event_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("deployer_name", sa.String(255), nullable=True),
            sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("custom_fields", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
            sa.ForeignKeyConstraint(["build_id"], ["build.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["release_id"], ["release.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("tenant_id", "event_id", name="uq_deployment_tenant_event"),
        )
        op.create_index("ix_deployment_tenant_id", "deployment", ["tenant_id"])
        op.create_index("ix_deployment_build_id", "deployment", ["build_id"])
        op.create_index("ix_deployment_environment_id", "deployment", ["environment_id"])
        op.create_index("ix_deployment_release_id", "deployment", ["release_id"])
        op.create_index("ix_deployment_change_request_id", "deployment", ["change_request_id"])

    # ESSV changes — rename build_id → build_identifier, add build_fk_id FK.
    if _column_exists(conn, "environment_subsystem_version", "build_id"):
        op.alter_column("environment_subsystem_version", "build_id", new_column_name="build_identifier")
    if not _column_exists(conn, "environment_subsystem_version", "build_fk_id"):
        op.add_column(
            "environment_subsystem_version",
            sa.Column("build_fk_id", sa.Integer(), nullable=True),
        )
        op.create_foreign_key(
            "fk_essv_build_fk", "environment_subsystem_version", "build",
            ["build_fk_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index(
            "ix_essv_build_fk_id", "environment_subsystem_version", ["build_fk_id"]
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _column_exists(conn, "environment_subsystem_version", "build_fk_id"):
        op.drop_index("ix_essv_build_fk_id", table_name="environment_subsystem_version")
        op.drop_constraint("fk_essv_build_fk", "environment_subsystem_version", type_="foreignkey")
        op.drop_column("environment_subsystem_version", "build_fk_id")
    if _column_exists(conn, "environment_subsystem_version", "build_identifier"):
        op.alter_column("environment_subsystem_version", "build_identifier", new_column_name="build_id")

    if _table_exists(conn, "deployment"):
        op.drop_table("deployment")
    if _table_exists(conn, "build"):
        op.drop_table("build")
    if _table_exists(conn, "api_key"):
        op.drop_table("api_key")
```

- [ ] **Step 3: Apply the migration**

```bash
cd backend && uv run alembic upgrade head 2>&1 | tail -10
```

Expected: `Running upgrade p3s8gateduedate -> p4s1builddeploy`. No errors.

- [ ] **Step 4: Verify migration head**

```bash
cd backend && uv run alembic heads 2>&1 | tail -3
```

Expected: `p4s1builddeploy (head)`.

- [ ] **Step 5: Run full backend suite**

```bash
cd backend && uv run pytest -x -q 2>&1 | tail -5
```

Expected: PASS. If any test references `environment_subsystem_version.build_id` as a column (not a string), rename to `build_identifier` in those tests. The ESSV model isn't updated yet — do it in Step 6 below.

- [ ] **Step 6: Update the ESSV model to match the renamed column**

In `backend/app/db/models/version.py` rename the attribute on the ORM model (keeps parity with the DB):

```python
class EnvironmentSubSystemVersion(Base):
    __tablename__ = "environment_subsystem_version"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    build_identifier: Mapped[str] = mapped_column(String(200), nullable=False)
    build_fk_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("build.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version_label: Mapped[str] = mapped_column(String(200), nullable=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenant.id"), nullable=False, index=True
    )
    environment: Mapped["Environment"] = relationship("Environment")  # type: ignore[name-defined]
    subsystem: Mapped["SubSystem"] = relationship("SubSystem")  # type: ignore[name-defined]

    __table_args__ = (
        Index("ix_env_sub_version_lookup", "environment_id", "subsystem_id"),
    )
```

Also update `Optional` / `String` imports at the top of the file if not already present. Then re-run the full suite. If any existing test or service references `row.build_id`, rename it to `row.build_identifier`. Commit all those grep-and-replace changes together with this step.

- [ ] **Step 7: Commit**

```bash
git add backend/app/db/migrations/versions/20260424_1200_p4s1_build_deployment.py backend/app/db/models/version.py
# plus any test/service files grep-replaced in step 6
git commit -m "feat(phase-4): migrate api_key + build + deployment tables; rename ESSV build_id -> build_identifier"
```

---

## Task 5: Extend `VALID_ENTITY_TYPES` to include `build` and `deployment`

**Files:**
- Modify: `backend/app/api/v1/schemas/custom_field.py`

- [ ] **Step 1: Write a test**

Create `backend/tests/test_custom_field_build_deployment_entity_types.py`:

```python
"""build and deployment must be accepted entity_type values."""
import pytest
from pydantic import ValidationError

from app.api.v1.schemas.custom_field import CustomFieldDefinitionCreate


def test_build_entity_type_accepted():
    c = CustomFieldDefinitionCreate(
        entity_type="build", label="Scan ID", field_type="text",
    )
    assert c.entity_type == "build"


def test_deployment_entity_type_accepted():
    c = CustomFieldDefinitionCreate(
        entity_type="deployment", label="Blast Radius", field_type="text",
    )
    assert c.entity_type == "deployment"


def test_unknown_entity_type_rejected():
    with pytest.raises(ValidationError):
        CustomFieldDefinitionCreate(
            entity_type="not_a_thing", label="x", field_type="text",
        )
```

- [ ] **Step 2: Run — confirm first two fail, third passes**

```bash
cd backend && uv run pytest tests/test_custom_field_build_deployment_entity_types.py -v
```

Expected: first two FAIL with `entity_type must be one of: ...`; third PASS.

- [ ] **Step 3: Add the two values**

In `backend/app/api/v1/schemas/custom_field.py`, replace the `VALID_ENTITY_TYPES` set:

```python
VALID_ENTITY_TYPES = {
    "system",
    "subsystem",
    "environment",
    "booking",
    "change_request",
    "release",
    "release_change",
    "build",
    "deployment",
}
```

- [ ] **Step 4: Run — all three pass**

```bash
cd backend && uv run pytest tests/test_custom_field_build_deployment_entity_types.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/v1/schemas/custom_field.py backend/tests/test_custom_field_build_deployment_entity_types.py
git commit -m "feat(phase-4): accept build + deployment entity_types on CustomFieldDefinition"
```

---

## Task 6: Seed `Code Deployment` lifecycle template on tenant creation

**Files:**
- Modify: `backend/app/services/change_request_service.py` — add a third seed entry and extend `seed_default_lifecycles`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_code_deployment_lifecycle_seed.py`:

```python
"""Code Deployment lifecycle must be seeded for every new tenant."""
import pytest
from sqlalchemy import select

from app.db.models.lifecycle import LifecycleTemplate
from app.services import change_request_service


@pytest.mark.asyncio
async def test_code_deployment_lifecycle_seeded(db_session, tenant):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    await db_session.flush()

    row = (
        await db_session.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant.id,
                LifecycleTemplate.entity_type == "change_request",
                LifecycleTemplate.name == "Code Deployment",
            )
        )
    ).scalar_one()
    assert row.is_system is True
    state_keys = {s["key"] for s in row.definition["states"]}
    assert state_keys == {"created", "deployed", "failed"}
    # Exactly one initial state: created
    initial = [s for s in row.definition["states"] if s.get("is_initial")]
    assert len(initial) == 1 and initial[0]["key"] == "created"
    # Two terminal states: deployed + failed
    terminal = {s["key"] for s in row.definition["states"] if s.get("is_terminal")}
    assert terminal == {"deployed", "failed"}
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_code_deployment_lifecycle_seed.py -v
```

Expected: FAIL — the template doesn't exist.

- [ ] **Step 3: Add the seed entry**

In `backend/app/services/change_request_service.py`, find the existing seed list (look for `"Simple Approval"`). Add a third entry in the same shape:

```python
{
    "name": "Code Deployment",
    "is_system": True,
    "definition": {
        "states": [
            {"key": "created", "label": "Created", "is_initial": True, "is_terminal": False},
            {"key": "deployed", "label": "Deployed", "is_initial": False, "is_terminal": True},
            {"key": "failed", "label": "Failed", "is_initial": False, "is_terminal": True},
        ],
        "transitions": [
            {"from": "created", "to": "deployed", "roles": []},
            {"from": "created", "to": "failed", "roles": []},
        ],
        "field_permissions": {
            "created": {"standard_fields": {}, "custom_fields": {}},
            "deployed": {"standard_fields": {}, "custom_fields": {}},
            "failed": {"standard_fields": {}, "custom_fields": {}},
        },
    },
},
```

`roles: []` means "any authenticated caller can transition" — appropriate because only the webhook triggers transitions, and it's already authenticated by API key.

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_code_deployment_lifecycle_seed.py -v
```

Expected: PASS.

- [ ] **Step 5: Backfill existing tenants via the migration**

The existing dev DB already has at least one tenant seeded before this change. Add a data-migration step to the Task 4 migration file (edit — don't create a new revision). In `upgrade()` of `20260424_1200_p4s1_build_deployment.py`, add at the end:

```python
    # Per-tenant seed of the Code Deployment lifecycle template.
    # Idempotent: skip tenants where a template with the same
    # (tenant_id, entity_type, name) already exists.
    conn.execute(sa.text("""
        INSERT INTO lifecycle_template (
            tenant_id, entity_type, name, is_system, is_default, definition,
            created_at, updated_at
        )
        SELECT t.id, 'change_request', 'Code Deployment', true, false,
               :definition,
               now(), now()
        FROM tenant t
        WHERE NOT EXISTS (
            SELECT 1 FROM lifecycle_template lt
            WHERE lt.tenant_id = t.id
              AND lt.entity_type = 'change_request'
              AND lt.name = 'Code Deployment'
        )
    """), {
        "definition": sa.dialects.postgresql.json.dumps({
            "states": [
                {"key": "created", "label": "Created", "is_initial": True, "is_terminal": False},
                {"key": "deployed", "label": "Deployed", "is_initial": False, "is_terminal": True},
                {"key": "failed", "label": "Failed", "is_initial": False, "is_terminal": True},
            ],
            "transitions": [
                {"from": "created", "to": "deployed", "roles": []},
                {"from": "created", "to": "failed", "roles": []},
            ],
            "field_permissions": {
                "created": {"standard_fields": {}, "custom_fields": {}},
                "deployed": {"standard_fields": {}, "custom_fields": {}},
                "failed": {"standard_fields": {}, "custom_fields": {}},
            },
        }),
    })
```

Replace with a simpler form if `sa.dialects.postgresql.json.dumps` isn't available — use `json.dumps` from stdlib instead and cast in SQL: `CAST(:definition AS JSONB)`.

- [ ] **Step 6: Re-apply the migration**

```bash
cd backend && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: clean downgrade then clean upgrade.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/change_request_service.py backend/app/db/migrations/versions/20260424_1200_p4s1_build_deployment.py backend/tests/services/test_code_deployment_lifecycle_seed.py
git commit -m "feat(phase-4): seed Code Deployment lifecycle template + backfill existing tenants"
```

---

## Task 7: `ApiKeyService` — hash, create, authenticate, revoke

**Files:**
- Create: `backend/app/services/api_key_service.py`
- Create: `backend/tests/services/test_api_key_service.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/services/test_api_key_service.py`:

```python
"""ApiKeyService — generate, authenticate, revoke, scope check."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services import api_key_service


@pytest.mark.asyncio
async def test_create_returns_raw_key_once_and_stores_hash_only(db_session, tenant, user):
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    assert raw.startswith("em_")
    assert len(raw) > 30
    # Stored value is a SHA-256 hex digest, 64 chars
    assert len(key.key_hash) == 64
    assert key.key_hash != raw


@pytest.mark.asyncio
async def test_authenticate_accepts_valid_key(db_session, tenant, user):
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.flush()

    authed = await api_key_service.authenticate(db_session, raw)
    assert authed.id == key.id


@pytest.mark.asyncio
async def test_authenticate_rejects_unknown_key(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, "em_notreal")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_rejects_expired_key(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Expired", scopes=["webhooks:deployment"],
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, raw)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_authenticate_rejects_revoked_key(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Dead", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    await api_key_service.revoke_key(db_session, tenant_id=tenant.id, key_id=key.id)
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await api_key_service.authenticate(db_session, raw)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_require_scope_passes_and_fails(db_session, tenant, user):
    from fastapi import HTTPException
    key, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Narrow", scopes=["webhooks:deployment"],
    )
    await db_session.flush()
    authed = await api_key_service.authenticate(db_session, raw)
    api_key_service.require_scope(authed, "webhooks:deployment")
    with pytest.raises(HTTPException) as exc:
        api_key_service.require_scope(authed, "admin:write")
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_api_key_service.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the service**

`backend/app/services/api_key_service.py`:

```python
"""ApiKey service — raw key generation + SHA-256 hashing + auth."""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey


RAW_PREFIX = "em_"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _generate_raw() -> str:
    return RAW_PREFIX + secrets.token_urlsafe(32)


async def create_key(
    db: AsyncSession,
    tenant_id: int,
    created_by: int,
    name: str,
    scopes: list[str],
    expires_at: Optional[datetime] = None,
) -> tuple[ApiKey, str]:
    """Generate + persist an API key. Returns the ORM row AND the raw key
    (which must be shown to the user once and never stored)."""
    raw = _generate_raw()
    key = ApiKey(
        tenant_id=tenant_id,
        key_hash=_hash(raw),
        name=name,
        scopes=scopes,
        created_by=created_by,
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()
    return key, raw


async def list_keys(db: AsyncSession, tenant_id: int) -> list[ApiKey]:
    rows = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.tenant_id == tenant_id,
                ApiKey.deleted_at.is_(None),
            ).order_by(ApiKey.id.desc())
        )
    ).scalars().all()
    return list(rows)


async def revoke_key(db: AsyncSession, tenant_id: int, key_id: int) -> None:
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.tenant_id == tenant_id,
                ApiKey.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key.deleted_at = datetime.now(timezone.utc)
    await db.flush()


async def authenticate(db: AsyncSession, raw: str) -> ApiKey:
    """Look up a raw key by hash. Raises 401 if missing/expired/revoked."""
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.key_hash == _hash(raw),
                ApiKey.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if key.expires_at is not None:
        expires = key.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key expired")
    return key


def require_scope(key: ApiKey, scope: str) -> None:
    if scope not in (key.scopes or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"API key is missing required scope '{scope}'",
        )
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_api_key_service.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/api_key_service.py backend/tests/services/test_api_key_service.py
git commit -m "feat(phase-4): ApiKeyService — create/authenticate/revoke/scope check"
```

---

## Task 8: `api_key_auth` FastAPI dependency

**Files:**
- Modify: `backend/app/core/security.py` — add the dependency factory

- [ ] **Step 1: Write a failing integration test**

Create `backend/tests/integration/test_api_key_auth_dep.py`:

```python
"""api_key_auth FastAPI dependency — 401/403 behaviour."""
import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import api_key_service


def _build_app(db_session):
    r = APIRouter()

    @r.get("/_probe")
    async def probe(key=Depends(api_key_auth(required_scope="webhooks:deployment"))):
        return {"tenant_id": key.tenant_id, "scopes": key.scopes}

    app = FastAPI()
    app.include_router(r)

    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    return app


@pytest.mark.asyncio
async def test_missing_header_401(db_session):
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_key_with_scope_200(db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe", headers={"X-Api-Key": raw})
        assert r.status_code == 200
        assert r.json()["tenant_id"] == tenant.id


@pytest.mark.asyncio
async def test_wrong_scope_403(db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["other:scope"],
    )
    await db_session.commit()
    app = _build_app(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/_probe", headers={"X-Api-Key": raw})
        assert r.status_code == 403
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_api_key_auth_dep.py -v
```

Expected: `ImportError` — `api_key_auth` not yet exported from `security`.

- [ ] **Step 3: Add the dependency factory**

In `backend/app/core/security.py`, add at the bottom:

```python
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.services import api_key_service


def api_key_auth(required_scope: str):
    """FastAPI dependency factory. Returns a dependency that requires a
    valid X-Api-Key header whose key has the given scope."""
    async def _dep(
        x_api_key: str | None = Header(default=None),
        db: AsyncSession = Depends(get_db),
    ):
        from datetime import datetime, timezone as _tz
        if not x_api_key:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing API key")
        key = await api_key_service.authenticate(db, x_api_key)
        api_key_service.require_scope(key, required_scope)
        # Bump last_used_at inline — small write, still part of the request
        # transaction; get_db auto-commits on success.
        key.last_used_at = datetime.now(_tz.utc)
        await db.flush()
        return key
    return _dep
```

Place the imports at the top of the file next to the existing imports if any duplicate.

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_api_key_auth_dep.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/security.py backend/tests/integration/test_api_key_auth_dep.py
git commit -m "feat(phase-4): api_key_auth FastAPI dependency factory"
```

---

## Task 9: API key admin endpoints

**Files:**
- Create: `backend/app/api/v1/api_keys.py`
- Modify: `backend/app/main.py` — register the router

- [ ] **Step 1: Write failing integration tests**

Create `backend/tests/integration/test_api_keys_api.py`:

```python
"""/api/v1/api-keys — create (raw shown once), list, revoke."""
import pytest


@pytest.mark.asyncio
async def test_create_list_revoke_roundtrip(client, auth_headers):
    # Create
    r = await client.post(
        "/api/v1/api-keys", headers=auth_headers,
        json={"name": "CI", "scopes": ["webhooks:deployment"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "CI"
    assert body["raw_key"].startswith("em_")
    key_id = body["id"]

    # List — raw_key MUST NOT appear
    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(k["id"] == key_id for k in items)
    for k in items:
        assert "raw_key" not in k
        assert "key_hash" not in k

    # Revoke
    r = await client.delete(f"/api/v1/api-keys/{key_id}", headers=auth_headers)
    assert r.status_code == 204

    # List — no longer appears
    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert all(k["id"] != key_id for k in r.json())
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_api_keys_api.py -v
```

Expected: 404 on the first POST — router not mounted yet.

- [ ] **Step 3: Create the router**

`backend/app/api/v1/api_keys.py`:

```python
"""API key CRUD — tenant-admin only. Raw key shown once on create."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_tenant_admin
from app.db.base import get_db
from app.db.models.user import User
from app.services import api_key_service
from app.api.v1.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead


router = APIRouter()


def _to_read(k) -> ApiKeyRead:
    return ApiKeyRead.model_validate({
        "id": k.id,
        "name": k.name,
        "scopes": k.scopes or [],
        "created_by": k.created_by,
        "created_by_username": None,  # hydrated below
        "last_used_at": k.last_used_at,
        "expires_at": k.expires_at,
        "created_at": k.created_at,
    })


@router.get("", response_model=list[ApiKeyRead])
async def list_keys(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    keys = await api_key_service.list_keys(db, current_user.active_tenant_id)
    user_ids = {k.created_by for k in keys}
    usernames: dict[int, str] = {}
    if user_ids:
        rows = (
            await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        ).all()
        usernames = {r.id: r.username for r in rows}
    out = []
    for k in keys:
        item = _to_read(k)
        item.created_by_username = usernames.get(k.created_by)
        out.append(item)
    return out


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    key, raw = await api_key_service.create_key(
        db,
        tenant_id=current_user.active_tenant_id,
        created_by=current_user.id,
        name=data.name,
        scopes=data.scopes,
        expires_at=data.expires_at,
    )
    item = _to_read(key)
    return ApiKeyCreated(**item.model_dump(), raw_key=raw)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    await api_key_service.revoke_key(
        db, tenant_id=current_user.active_tenant_id, key_id=key_id,
    )
    return None
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, next to other `include_router` calls:

```python
from app.api.v1 import api_keys as api_keys_router

app.include_router(api_keys_router.router, prefix="/api/v1/api-keys", tags=["api-keys"])
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_api_keys_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/api_keys.py backend/app/main.py backend/tests/integration/test_api_keys_api.py
git commit -m "feat(phase-4): /api/v1/api-keys CRUD (tenant admin, raw key shown once)"
```

---

## Task 10: `BuildService.upsert_build`

**Files:**
- Create: `backend/app/services/build_service.py`
- Create: `backend/tests/services/test_build_service.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/services/test_build_service.py`:

```python
"""BuildService — upsert, validate custom fields, re-post updates pipeline_steps."""
from datetime import datetime, timezone

import pytest

from app.api.v1.schemas.build import BuildPayload
from app.db.models.custom_field import CustomFieldDefinition
from app.services import build_service


async def _make_subsystem(db_session, tenant_id):
    from app.db.models.system import System, SubSystem
    sys = System(tenant_id=tenant_id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant_id, system_id=sys.id, name="orders-api")
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest.mark.asyncio
async def test_upsert_inserts_new_build(db_session, tenant):
    sub = await _make_subsystem(db_session, tenant.id)
    payload = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )
    build = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload,
    )
    await db_session.flush()
    assert build.id is not None
    assert build.git_sha == "abc123"
    assert build.pipeline_steps == []


@pytest.mark.asyncio
async def test_upsert_updates_existing_build(db_session, tenant):
    sub = await _make_subsystem(db_session, tenant.id)
    payload1 = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        pipeline_steps=[],
    )
    first = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload1,
    )
    await db_session.flush()

    payload2 = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        pipeline_steps=[{"name": "test", "status": "success"}],
        jira_tickets=["PROJ-1"],
    )
    second = await build_service.upsert_build(
        db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload2,
    )
    await db_session.flush()

    assert second.id == first.id
    assert len(second.pipeline_steps) == 1
    assert second.jira_tickets == ["PROJ-1"]


@pytest.mark.asyncio
async def test_upsert_validates_custom_fields(db_session, tenant):
    from fastapi import HTTPException
    # Seed a required custom field definition
    defn = CustomFieldDefinition(
        tenant_id=tenant.id, entity_type="build", field_key="scan_id",
        label="Scan ID", field_type="text", required=True,
    )
    db_session.add(defn)
    sub = await _make_subsystem(db_session, tenant.id)
    await db_session.flush()

    payload = BuildPayload(
        git_sha="abc123",
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        custom_fields={},  # missing required field
    )
    with pytest.raises(HTTPException) as exc:
        await build_service.upsert_build(
            db_session, tenant_id=tenant.id, subsystem_id=sub.id, data=payload,
        )
    assert exc.value.status_code == 422
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_build_service.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the service**

`backend/app/services/build_service.py`:

```python
"""BuildService — upsert builds by (tenant, subsystem, git_sha, build_number)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.build import BuildPayload
from app.db.models.build import Build
from app.services import custom_field_service


async def upsert_build(
    db: AsyncSession,
    tenant_id: int,
    subsystem_id: int,
    data: BuildPayload,
    release_id: int | None = None,
) -> Build:
    """Insert or update a Build row, keyed on
    (tenant_id, subsystem_id, git_sha, build_number).

    Pipeline steps, jira tickets, custom fields, and finished_at are
    replaced wholesale on update — callers own the canonical view."""
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "build", data.custom_fields or {},
    )

    existing = (
        await db.execute(
            select(Build).where(
                Build.tenant_id == tenant_id,
                Build.subsystem_id == subsystem_id,
                Build.git_sha == data.git_sha,
                Build.build_number == data.build_number,
                Build.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        build = Build(
            tenant_id=tenant_id,
            subsystem_id=subsystem_id,
            release_id=release_id,
            git_sha=data.git_sha,
            git_branch=data.git_branch,
            build_number=data.build_number,
            commit_timestamp=data.commit_timestamp,
            build_started_at=data.build_started_at,
            build_finished_at=data.build_finished_at,
            jira_tickets=list(data.jira_tickets or []),
            pipeline_steps=[s.model_dump(mode="json") for s in data.pipeline_steps],
            custom_fields=dict(data.custom_fields or {}),
        )
        db.add(build)
        await db.flush()
        return build

    existing.git_branch = data.git_branch
    existing.build_started_at = data.build_started_at
    existing.build_finished_at = data.build_finished_at
    existing.jira_tickets = list(data.jira_tickets or [])
    existing.pipeline_steps = [s.model_dump(mode="json") for s in data.pipeline_steps]
    existing.custom_fields = dict(data.custom_fields or {})
    if release_id is not None:
        existing.release_id = release_id
    await db.flush()
    return existing
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_build_service.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/build_service.py backend/tests/services/test_build_service.py
git commit -m "feat(phase-4): BuildService.upsert_build + custom-field validation"
```

---

## Task 11: `ChangeRequestService.create_code_deployment`

**Files:**
- Modify: `backend/app/services/change_request_service.py`
- Create: `backend/tests/services/test_change_request_code_deployment.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/services/test_change_request_code_deployment.py`:

```python
"""ChangeRequestService.create_code_deployment — auto CR for webhook deployments."""
import pytest
from sqlalchemy import select

from app.db.models.change_request import ChangeRequest, ChangeType
from app.services import change_request_service


@pytest.mark.asyncio
async def test_create_code_deployment_cr(db_session, tenant, user):
    # Seed the Code Deployment template.
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    await db_session.flush()

    cr = await change_request_service.create_code_deployment(
        db_session,
        tenant_id=tenant.id,
        raised_by=user.id,
        title="Deploy abc123 to sit",
        description="Automated via GitHub Actions",
    )
    await db_session.flush()

    row = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == cr.id)
    )).scalar_one()
    assert row.change_type == ChangeType.CODE_DEPLOYMENT
    assert row.state == "created"
    assert row.raised_by == user.id
    assert row.title.startswith("Deploy abc123")


@pytest.mark.asyncio
async def test_missing_template_raises(db_session, tenant, user):
    # No seed called — template should not exist.
    with pytest.raises(Exception):
        await change_request_service.create_code_deployment(
            db_session, tenant_id=tenant.id, raised_by=user.id,
            title="x", description="y",
        )
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_change_request_code_deployment.py -v
```

Expected: `AttributeError: module has no attribute 'create_code_deployment'`.

- [ ] **Step 3: Add the helper**

In `backend/app/services/change_request_service.py`, add (anywhere after the existing `create_change_request`):

```python
async def create_code_deployment(
    db: AsyncSession,
    tenant_id: int,
    raised_by: int,
    title: str,
    description: str,
) -> ChangeRequest:
    """Create a ChangeRequest wired to the Code Deployment lifecycle.

    Caller is the webhook ingest — the CR records the fact of a deployment.
    State starts at 'created'; the ingest flow transitions it to
    'deployed' or 'failed' based on webhook status.
    """
    from app.db.models.lifecycle import LifecycleTemplate
    tpl = (
        await db.execute(
            select(LifecycleTemplate).where(
                LifecycleTemplate.tenant_id == tenant_id,
                LifecycleTemplate.entity_type == "change_request",
                LifecycleTemplate.name == "Code Deployment",
                LifecycleTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if tpl is None:
        raise RuntimeError(
            f"Code Deployment lifecycle template missing for tenant {tenant_id}. "
            "Run the seed before creating code-deployment CRs."
        )

    cr = ChangeRequest(
        tenant_id=tenant_id,
        title=title,
        description=description,
        change_type=ChangeType.CODE_DEPLOYMENT,
        state="created",
        lifecycle_template_id=tpl.id,
        raised_by=raised_by,
    )
    db.add(cr)
    await db.flush()

    await publish_event(
        db,
        event_type="ChangeRequestCreated",
        aggregate_id=cr.id,
        aggregate_type="ChangeRequest",
        payload={"id": cr.id, "change_type": "code_deployment"},
        tenant_id=tenant_id,
    )
    return cr
```

Make sure `publish_event` is already imported at the top of the file. If not, add:

```python
from app.core.events import publish_event
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_change_request_code_deployment.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/change_request_service.py backend/tests/services/test_change_request_code_deployment.py
git commit -m "feat(phase-4): ChangeRequestService.create_code_deployment helper"
```

---

## Task 12: `DeploymentService.ingest` — happy path (status=success, no auto-CR)

**Files:**
- Create: `backend/app/services/deployment_service.py`
- Create: `backend/tests/services/test_deployment_service_happy_path.py`

- [ ] **Step 1: Write failing test**

`backend/tests/services/test_deployment_service_happy_path.py`:

```python
"""DeploymentService.ingest — success path with caller-supplied CR id."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import deployment_service


async def _setup(db_session, tenant, user):
    """Create minimal system/subsystem/env/CR scaffolding."""
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.services import change_request_service

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()

    cr = ChangeRequest(
        tenant_id=tenant.id, title="Manual CR", description="x",
        change_type=ChangeType.CODE_DEPLOYMENT, state="created",
        raised_by=user.id,
    )
    db_session.add(cr)
    await db_session.flush()
    return {"system": sys, "subsystem": sub, "environment": env, "cr": cr}


@pytest.mark.asyncio
async def test_ingest_success_creates_build_deployment_and_version_row(
    db_session, tenant, user,
):
    ctx = await _setup(db_session, tenant, user)
    payload = DeploymentWebhookPayload(
        event_id=uuid4(),
        system_slug="orders",
        subsystem_slug="orders-api",
        environment_slug="sit",
        status="success",
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        change_request_id=ctx["cr"].id,
        deployer_name="github.actor:alice",
        build=BuildPayload(
            git_sha="abcdef1234567890",
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )
    result = await deployment_service.ingest(db_session, tenant.id, payload)
    await db_session.flush()

    assert result.replayed is False
    build = (await db_session.execute(
        select(Build).where(Build.id == result.build_id)
    )).scalar_one()
    assert build.git_sha == "abcdef1234567890"

    deployment = (await db_session.execute(
        select(Deployment).where(Deployment.id == result.deployment_id)
    )).scalar_one()
    assert deployment.status == "success"
    assert deployment.environment_id == ctx["environment"].id
    assert deployment.change_request_id == ctx["cr"].id

    version = (await db_session.execute(
        select(EnvironmentSubSystemVersion).where(
            EnvironmentSubSystemVersion.environment_id == ctx["environment"].id,
            EnvironmentSubSystemVersion.subsystem_id == ctx["subsystem"].id,
        )
    )).scalars().all()
    assert len(version) == 1
    assert version[0].build_fk_id == build.id
    assert version[0].build_identifier == "abcdef123456"  # first 12 chars
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_happy_path.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement minimal ingest**

`backend/app/services/deployment_service.py`:

```python
"""DeploymentService — webhook ingest flow.

ingest() is the single transactional entry point. Slug resolution, build
upsert, CR resolution, deployment insert, side effects, event emission —
all in one pass.
"""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.deployment import DeploymentIngestResult, DeploymentWebhookPayload
from app.core.events import publish_event
from app.db.models.build import Build
from app.db.models.deployment import Deployment
from app.db.models.environment import Environment
from app.db.models.system import System, SubSystem
from app.db.models.version import EnvironmentSubSystemVersion
from app.services import build_service, custom_field_service


ALLOWED_STATUSES = {"pending", "in_progress", "success", "failed", "rolled_back"}


async def _resolve_subsystem(
    db: AsyncSession, tenant_id: int, system_slug: str, subsystem_slug: str
) -> int:
    sys_id = (await db.execute(
        select(System.id).where(
            System.tenant_id == tenant_id,
            System.name == system_slug,
            System.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if sys_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown system_slug '{system_slug}'")
    sub_id = (await db.execute(
        select(SubSystem.id).where(
            SubSystem.tenant_id == tenant_id,
            SubSystem.system_id == sys_id,
            SubSystem.name == subsystem_slug,
            SubSystem.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if sub_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown subsystem_slug '{subsystem_slug}' for system '{system_slug}'")
    return sub_id


async def _resolve_environment(db: AsyncSession, tenant_id: int, slug: str) -> int:
    env_id = (await db.execute(
        select(Environment.id).where(
            Environment.tenant_id == tenant_id,
            Environment.name == slug,
            Environment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if env_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown environment_slug '{slug}'")
    return env_id


async def ingest(
    db: AsyncSession,
    tenant_id: int,
    payload: DeploymentWebhookPayload,
) -> DeploymentIngestResult:
    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown status '{payload.status}'")

    subsystem_id = await _resolve_subsystem(
        db, tenant_id, payload.system_slug, payload.subsystem_slug,
    )
    environment_id = await _resolve_environment(db, tenant_id, payload.environment_slug)

    # Validate deployment-level custom fields before doing any writes.
    await custom_field_service.validate_custom_fields(
        db, tenant_id, "deployment", payload.deployment_custom_fields or {},
    )

    # Upsert build.
    build = await build_service.upsert_build(
        db, tenant_id=tenant_id, subsystem_id=subsystem_id, data=payload.build,
        release_id=payload.release_id,
    )

    if payload.change_request_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "change_request_id is required — auto-create path not wired yet")

    # Insert deployment.
    completed_at = payload.deployed_at if payload.status in {"success", "failed"} else None
    deployment = Deployment(
        tenant_id=tenant_id,
        build_id=build.id,
        environment_id=environment_id,
        release_id=payload.release_id or build.release_id,
        change_request_id=payload.change_request_id,
        event_id=payload.event_id,
        deployer_name=payload.deployer_name,
        deployed_at=payload.deployed_at,
        completed_at=completed_at,
        status=payload.status,
        custom_fields=dict(payload.deployment_custom_fields or {}),
    )
    db.add(deployment)
    await db.flush()

    if payload.status == "success":
        # Audit-trail insert for the installed version.
        version_label = payload.build.build_number or payload.build.git_sha[:8]
        db.add(EnvironmentSubSystemVersion(
            tenant_id=tenant_id,
            environment_id=environment_id,
            subsystem_id=subsystem_id,
            build_identifier=payload.build.git_sha[:12],
            build_fk_id=build.id,
            version_label=version_label,
        ))
        await db.flush()

    await publish_event(
        db,
        event_type={
            "pending": "DeploymentStarted",
            "in_progress": "DeploymentStarted",
            "success": "DeploymentCompleted",
            "failed": "DeploymentFailed",
            "rolled_back": "DeploymentRolledBack",
        }[payload.status],
        aggregate_id=deployment.id,
        aggregate_type="Deployment",
        payload={
            "deployment_id": deployment.id,
            "build_id": build.id,
            "environment_id": environment_id,
            "release_id": deployment.release_id,
            "change_request_id": deployment.change_request_id,
            "status": deployment.status,
        },
        tenant_id=tenant_id,
    )

    return DeploymentIngestResult(
        deployment_id=deployment.id,
        build_id=build.id,
        change_request_id=deployment.change_request_id,
        replayed=False,
    )
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_happy_path.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/deployment_service.py backend/tests/services/test_deployment_service_happy_path.py
git commit -m "feat(phase-4): DeploymentService.ingest — happy path with supplied CR"
```

---

## Task 13: Auto-create CR when the payload doesn't carry one

**Files:**
- Modify: `backend/app/services/deployment_service.py`
- Create: `backend/tests/services/test_deployment_service_auto_cr.py`

- [ ] **Step 1: Write failing test**

`backend/tests/services/test_deployment_service_auto_cr.py`:

```python
"""If the webhook omits change_request_id, ingest auto-creates a code_deployment CR."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.change_request import ChangeRequest, ChangeType
from app.services import change_request_service, deployment_service


@pytest.mark.asyncio
async def test_ingest_auto_creates_cr_when_omitted(db_session, tenant, user):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()

    payload = DeploymentWebhookPayload(
        event_id=uuid4(),
        system_slug="orders",
        subsystem_slug="orders-api",
        environment_slug="sit",
        status="success",
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        change_request_id=None,  # not supplied
        build=BuildPayload(
            git_sha="deadbeef1234",
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )

    result = await deployment_service.ingest(
        db_session, tenant.id, payload, raised_by_user_id=user.id,
    )
    await db_session.flush()

    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == result.change_request_id)
    )).scalar_one()
    assert cr.change_type == ChangeType.CODE_DEPLOYMENT
    assert cr.state in {"created", "deployed"}  # happy path will transition to deployed in Task 14
    assert cr.raised_by == user.id
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_auto_cr.py -v
```

Expected: FAIL with `change_request_id is required — auto-create path not wired yet` or TypeError about missing `raised_by_user_id` param.

- [ ] **Step 3: Rewire ingest — accept `raised_by_user_id` and auto-create**

In `backend/app/services/deployment_service.py`, change the `ingest` signature and body:

```python
async def ingest(
    db: AsyncSession,
    tenant_id: int,
    payload: DeploymentWebhookPayload,
    raised_by_user_id: int,
) -> DeploymentIngestResult:
```

Replace the block that raises `change_request_id is required` with:

```python
    if payload.change_request_id is not None:
        from app.db.models.change_request import ChangeRequest
        cr = (await db.execute(
            select(ChangeRequest).where(
                ChangeRequest.id == payload.change_request_id,
                ChangeRequest.tenant_id == tenant_id,
                ChangeRequest.deleted_at.is_(None),
            )
        )).scalar_one_or_none()
        if cr is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"change_request_id {payload.change_request_id} not found")
        change_request_id = cr.id
    else:
        from app.services import change_request_service
        cr = await change_request_service.create_code_deployment(
            db,
            tenant_id=tenant_id,
            raised_by=raised_by_user_id,
            title=f"Deploy {payload.build.git_sha[:8]} → {payload.environment_slug}",
            description=f"Auto-created from webhook event {payload.event_id}",
        )
        change_request_id = cr.id
```

Then replace `change_request_id=payload.change_request_id` in the Deployment ctor with `change_request_id=change_request_id`.

- [ ] **Step 4: Update Task 12's earlier test to pass `raised_by_user_id`**

Edit `backend/tests/services/test_deployment_service_happy_path.py` — the `ingest` call must now include `raised_by_user_id=user.id`:

```python
    result = await deployment_service.ingest(
        db_session, tenant.id, payload, raised_by_user_id=user.id,
    )
```

- [ ] **Step 5: Run — confirm both pass**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_happy_path.py tests/services/test_deployment_service_auto_cr.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/deployment_service.py backend/tests/services/test_deployment_service_happy_path.py backend/tests/services/test_deployment_service_auto_cr.py
git commit -m "feat(phase-4): DeploymentService.ingest — auto-create code_deployment CR when omitted"
```

---

## Task 14: Idempotency on `event_id` + status-transition rules + CR transition side effects

**Files:**
- Modify: `backend/app/services/deployment_service.py`
- Create: `backend/tests/services/test_deployment_service_transitions.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/services/test_deployment_service_transitions.py`:

```python
"""Idempotency + status-transition table + CR state side effects."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.api.v1.schemas.build import BuildPayload
from app.api.v1.schemas.deployment import DeploymentWebhookPayload
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.services import change_request_service, deployment_service


async def _prep(db_session, tenant, user):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()
    return sub, env


def _payload(event_id, status, sha="aaa111"):
    return DeploymentWebhookPayload(
        event_id=event_id,
        system_slug="Orders",  # resolver is case-sensitive — match seeded name
        subsystem_slug="orders-api",
        environment_slug="sit",
        status=status,
        deployed_at=datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc),
        build=BuildPayload(
            git_sha=sha,
            build_number="#1",
            commit_timestamp=datetime(2026, 4, 23, 14, tzinfo=timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_replay_returns_replayed_true(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    ev = uuid4()
    r1 = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    r2 = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    assert r2.deployment_id == r1.deployment_id
    assert r2.replayed is True

    rows = (await db_session.execute(
        select(Deployment).where(Deployment.event_id == ev)
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_success_transitions_cr_to_deployed(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(uuid4(), "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == r.change_request_id)
    )).scalar_one()
    assert cr.state == "deployed"


@pytest.mark.asyncio
async def test_failed_transitions_cr_to_failed(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(uuid4(), "failed"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    cr = (await db_session.execute(
        select(ChangeRequest).where(ChangeRequest.id == r.change_request_id)
    )).scalar_one()
    assert cr.state == "failed"


@pytest.mark.asyncio
async def test_pending_to_success_via_update(db_session, tenant, user):
    await _prep(db_session, tenant, user)
    ev = uuid4()
    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "pending"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    r = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    deployment = (await db_session.execute(
        select(Deployment).where(Deployment.event_id == ev)
    )).scalar_one()
    assert deployment.status == "success"


@pytest.mark.asyncio
async def test_illegal_transition_rejected(db_session, tenant, user):
    from fastapi import HTTPException
    await _prep(db_session, tenant, user)
    ev = uuid4()
    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    with pytest.raises(HTTPException) as exc:
        await deployment_service.ingest(
            db_session, tenant.id, _payload(ev, "pending"), raised_by_user_id=user.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_rolled_back_emits_event_and_leaves_cr_alone(db_session, tenant, user):
    from app.db.models.event_log import EventLog
    from sqlalchemy import select as _sel
    await _prep(db_session, tenant, user)
    ev = uuid4()
    first = await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "success"), raised_by_user_id=user.id,
    )
    await db_session.flush()
    # CR should be 'deployed' after success.
    cr_before = (await db_session.execute(
        _sel(ChangeRequest).where(ChangeRequest.id == first.change_request_id)
    )).scalar_one()
    assert cr_before.state == "deployed"

    await deployment_service.ingest(
        db_session, tenant.id, _payload(ev, "rolled_back"), raised_by_user_id=user.id,
    )
    await db_session.flush()

    dep = (await db_session.execute(
        _sel(Deployment).where(Deployment.event_id == ev)
    )).scalar_one()
    assert dep.status == "rolled_back"

    # CR state unchanged — rollback is an event, not a state transition.
    cr_after = (await db_session.execute(
        _sel(ChangeRequest).where(ChangeRequest.id == first.change_request_id)
    )).scalar_one()
    assert cr_after.state == "deployed"

    # DeploymentRolledBack event emitted to the outbox.
    events = (await db_session.execute(
        _sel(EventLog).where(
            EventLog.tenant_id == tenant.id,
            EventLog.event_type == "DeploymentRolledBack",
            EventLog.aggregate_id == dep.id,
        )
    )).scalars().all()
    assert len(events) == 1
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_transitions.py -v
```

Expected: multiple failures — replay inserts duplicates, CR state isn't transitioned, no transition table enforced.

- [ ] **Step 3: Rewire ingest with idempotency + transitions**

In `backend/app/services/deployment_service.py`, add at module top:

```python
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"pending", "in_progress", "success", "failed"},
    "in_progress": {"in_progress", "success", "failed"},
    "success": {"success", "rolled_back"},
    "failed": {"failed", "rolled_back"},
    "rolled_back": {"rolled_back"},
}
```

Replace the `ingest` body so it: (a) short-circuits on unchanged replay; (b) enforces transitions when an existing deployment is found; (c) transitions the CR as a side effect on terminal statuses.

Minimum body (replace the ingest function entirely — keep signature):

```python
async def ingest(
    db: AsyncSession,
    tenant_id: int,
    payload: DeploymentWebhookPayload,
    raised_by_user_id: int,
) -> DeploymentIngestResult:
    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Unknown status '{payload.status}'")

    # Idempotency lookup by (tenant_id, event_id).
    existing = (await db.execute(
        select(Deployment).where(
            Deployment.tenant_id == tenant_id,
            Deployment.event_id == payload.event_id,
        )
    )).scalar_one_or_none()

    if existing is not None and existing.status == payload.status:
        return DeploymentIngestResult(
            deployment_id=existing.id,
            build_id=existing.build_id,
            change_request_id=existing.change_request_id,
            replayed=True,
        )

    if existing is not None:
        allowed = ALLOWED_TRANSITIONS.get(existing.status, set())
        if payload.status not in allowed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Deployment status {existing.status} cannot transition to {payload.status}",
            )

    subsystem_id = await _resolve_subsystem(
        db, tenant_id, payload.system_slug, payload.subsystem_slug,
    )
    environment_id = await _resolve_environment(db, tenant_id, payload.environment_slug)

    await custom_field_service.validate_custom_fields(
        db, tenant_id, "deployment", payload.deployment_custom_fields or {},
    )

    build = await build_service.upsert_build(
        db, tenant_id=tenant_id, subsystem_id=subsystem_id, data=payload.build,
        release_id=payload.release_id,
    )

    # CR resolution (only when creating a new deployment — transitions reuse
    # the existing deployment's CR).
    if existing is None:
        if payload.change_request_id is not None:
            from app.db.models.change_request import ChangeRequest
            cr = (await db.execute(
                select(ChangeRequest).where(
                    ChangeRequest.id == payload.change_request_id,
                    ChangeRequest.tenant_id == tenant_id,
                    ChangeRequest.deleted_at.is_(None),
                )
            )).scalar_one_or_none()
            if cr is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    f"change_request_id {payload.change_request_id} not found")
            change_request_id = cr.id
        else:
            from app.services import change_request_service
            cr = await change_request_service.create_code_deployment(
                db,
                tenant_id=tenant_id,
                raised_by=raised_by_user_id,
                title=f"Deploy {payload.build.git_sha[:8]} → {payload.environment_slug}",
                description=f"Auto-created from webhook event {payload.event_id}",
            )
            change_request_id = cr.id
    else:
        change_request_id = existing.change_request_id

    completed_at = payload.deployed_at if payload.status in {"success", "failed"} else None

    if existing is None:
        deployment = Deployment(
            tenant_id=tenant_id,
            build_id=build.id,
            environment_id=environment_id,
            release_id=payload.release_id or build.release_id,
            change_request_id=change_request_id,
            event_id=payload.event_id,
            deployer_name=payload.deployer_name,
            deployed_at=payload.deployed_at,
            completed_at=completed_at,
            status=payload.status,
            custom_fields=dict(payload.deployment_custom_fields or {}),
        )
        db.add(deployment)
        await db.flush()
    else:
        deployment = existing
        deployment.status = payload.status
        deployment.completed_at = completed_at or deployment.completed_at
        await db.flush()

    # Side effects on terminal statuses.
    if payload.status == "success":
        version_label = payload.build.build_number or payload.build.git_sha[:8]
        db.add(EnvironmentSubSystemVersion(
            tenant_id=tenant_id,
            environment_id=environment_id,
            subsystem_id=subsystem_id,
            build_identifier=payload.build.git_sha[:12],
            build_fk_id=build.id,
            version_label=version_label,
        ))
        await db.flush()

    # Transition the linked CR on terminal statuses.
    if payload.status in {"success", "failed"}:
        from app.db.models.change_request import ChangeRequest
        cr = (await db.execute(
            select(ChangeRequest).where(ChangeRequest.id == change_request_id)
        )).scalar_one()
        target_state = "deployed" if payload.status == "success" else "failed"
        if cr.state != target_state:
            cr.state = target_state
            await db.flush()

    await publish_event(
        db,
        event_type={
            "pending": "DeploymentStarted",
            "in_progress": "DeploymentStarted",
            "success": "DeploymentCompleted",
            "failed": "DeploymentFailed",
            "rolled_back": "DeploymentRolledBack",
        }[payload.status],
        aggregate_id=deployment.id,
        aggregate_type="Deployment",
        payload={
            "deployment_id": deployment.id,
            "build_id": build.id,
            "environment_id": environment_id,
            "release_id": deployment.release_id,
            "change_request_id": change_request_id,
            "status": payload.status,
        },
        tenant_id=tenant_id,
    )

    return DeploymentIngestResult(
        deployment_id=deployment.id,
        build_id=build.id,
        change_request_id=change_request_id,
        replayed=False,
    )
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/services/test_deployment_service_transitions.py tests/services/test_deployment_service_happy_path.py tests/services/test_deployment_service_auto_cr.py -v
```

Expected: all passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/deployment_service.py backend/tests/services/test_deployment_service_transitions.py
git commit -m "feat(phase-4): DeploymentService.ingest — idempotency + transitions + CR side effects"
```

---

## Task 15: Webhook endpoint `POST /api/v1/webhooks/deployment`

**Files:**
- Create: `backend/app/api/v1/webhooks/__init__.py` (empty)
- Create: `backend/app/api/v1/webhooks/deployment.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_webhook_deployment.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_webhook_deployment.py`:

```python
"""/api/v1/webhooks/deployment — HTTP integration tests."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import api_key_service, change_request_service


async def _scaffold(db_session, tenant, user):
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="CI", scopes=["webhooks:deployment"],
    )
    await db_session.commit()
    return raw


def _body(event_id=None):
    return {
        "event_id": str(event_id or uuid4()),
        "system_slug": "Orders",
        "subsystem_slug": "orders-api",
        "environment_slug": "sit",
        "status": "success",
        "deployed_at": datetime(2026, 4, 23, 14, 30, tzinfo=timezone.utc).isoformat(),
        "build": {
            "git_sha": "cafef00d" * 4,
            "build_number": "#1",
            "commit_timestamp": datetime(2026, 4, 23, 14, tzinfo=timezone.utc).isoformat(),
        },
    }


@pytest.mark.asyncio
async def test_webhook_happy_path(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw},
        json=_body(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["replayed"] is False
    assert "deployment_id" in body


@pytest.mark.asyncio
async def test_webhook_replay(client, db_session, tenant, user):
    raw = await _scaffold(db_session, tenant, user)
    ev = uuid4()
    r1 = await client.post(
        "/api/v1/webhooks/deployment", headers={"X-Api-Key": raw}, json=_body(ev),
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/api/v1/webhooks/deployment", headers={"X-Api-Key": raw}, json=_body(ev),
    )
    assert r2.status_code == 200
    assert r2.json()["replayed"] is True
    assert r2.json()["deployment_id"] == r1.json()["deployment_id"]


@pytest.mark.asyncio
async def test_webhook_unauthenticated(client):
    r = await client.post("/api/v1/webhooks/deployment", json=_body())
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_wrong_scope(client, db_session, tenant, user):
    _, raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name="Narrow", scopes=["other"],
    )
    await db_session.commit()
    r = await client.post(
        "/api/v1/webhooks/deployment",
        headers={"X-Api-Key": raw}, json=_body(),
    )
    assert r.status_code == 403
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_webhook_deployment.py -v
```

Expected: 404 on the first POST — endpoint not registered.

- [ ] **Step 3: Create the webhook module**

First create the package file: `backend/app/api/v1/webhooks/__init__.py` (empty file).

Then `backend/app/api/v1/webhooks/deployment.py`:

```python
"""POST /api/v1/webhooks/deployment — CI/CD deployment ingestion."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import api_key_auth
from app.db.base import get_db
from app.services import deployment_service
from app.api.v1.schemas.deployment import (
    DeploymentIngestResult,
    DeploymentWebhookPayload,
)


router = APIRouter()


@router.post("/deployment", response_model=DeploymentIngestResult)
async def ingest_deployment(
    payload: DeploymentWebhookPayload,
    db: AsyncSession = Depends(get_db),
    api_key=Depends(api_key_auth(required_scope="webhooks:deployment")),
):
    return await deployment_service.ingest(
        db,
        tenant_id=api_key.tenant_id,
        payload=payload,
        raised_by_user_id=api_key.created_by,
    )
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`:

```python
from app.api.v1.webhooks import deployment as webhook_deployment_router

app.include_router(
    webhook_deployment_router.router,
    prefix="/api/v1/webhooks",
    tags=["webhooks"],
)
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_webhook_deployment.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/webhooks/__init__.py backend/app/api/v1/webhooks/deployment.py backend/app/main.py backend/tests/integration/test_webhook_deployment.py
git commit -m "feat(phase-4): POST /api/v1/webhooks/deployment — authenticated webhook ingest"
```

---

## Task 16: Build read endpoints

**Files:**
- Create: `backend/app/api/v1/builds.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_builds_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_builds_api.py`:

```python
"""GET /api/v1/builds + /{id} — JWT auth, filters, detail."""
from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    db_session.add(sub)
    await db_session.flush()
    b = Build(
        tenant_id=tenant.id, subsystem_id=sub.id, git_sha="deadbeef1234",
        build_number="#5", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(b)
    await db_session.commit()

    r = await client.get("/api/v1/builds", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(x["id"] == b.id for x in items)

    r = await client.get(f"/api/v1/builds/{b.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["git_sha"] == "deadbeef1234"


@pytest.mark.asyncio
async def test_filter_by_subsystem(client, auth_headers, db_session, tenant):
    from app.db.models.system import System, SubSystem
    from app.db.models.build import Build
    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub_a = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="a")
    sub_b = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="b")
    db_session.add_all([sub_a, sub_b])
    await db_session.flush()
    for sub, sha in [(sub_a, "aaaa"), (sub_b, "bbbb")]:
        db_session.add(Build(
            tenant_id=tenant.id, subsystem_id=sub.id, git_sha=sha * 4,
            build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
        ))
    await db_session.commit()

    r = await client.get(f"/api/v1/builds?subsystem_id={sub_a.id}", headers=auth_headers)
    shas = {x["git_sha"] for x in r.json()}
    assert shas == {"aaaa" * 4}
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_builds_api.py -v
```

Expected: 404.

- [ ] **Step 3: Create the router**

`backend/app/api/v1/builds.py`:

```python
"""GET /api/v1/builds — list + detail."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.build import Build
from app.api.v1.schemas.build import BuildRead


router = APIRouter()


@router.get("", response_model=list[BuildRead])
async def list_builds(
    subsystem_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    branch: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Build).where(
        Build.tenant_id == current_user.active_tenant_id,
        Build.deleted_at.is_(None),
    )
    if subsystem_id is not None:
        q = q.where(Build.subsystem_id == subsystem_id)
    if release_id is not None:
        q = q.where(Build.release_id == release_id)
    if branch is not None:
        q = q.where(Build.git_branch == branch)
    if date_from is not None:
        q = q.where(Build.commit_timestamp >= date_from)
    if date_to is not None:
        q = q.where(Build.commit_timestamp <= date_to)
    q = q.order_by(Build.commit_timestamp.desc()).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()
    return list(rows)


@router.get("/{build_id}", response_model=BuildRead)
async def get_build(
    build_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        select(Build).where(
            Build.id == build_id,
            Build.tenant_id == current_user.active_tenant_id,
            Build.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Build not found")
    return row
```

- [ ] **Step 4: Register**

In `backend/app/main.py`:

```python
from app.api.v1 import builds as builds_router

app.include_router(builds_router.router, prefix="/api/v1/builds", tags=["builds"])
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_builds_api.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/builds.py backend/app/main.py backend/tests/integration/test_builds_api.py
git commit -m "feat(phase-4): /api/v1/builds list + detail"
```

---

## Task 17: Deployment read endpoints + link-change + env deployments

**Files:**
- Create: `backend/app/api/v1/deployments.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/integration/test_deployments_api.py`

- [ ] **Step 1: Write failing tests**

`backend/tests/integration/test_deployments_api.py`:

```python
"""GET /api/v1/deployments + detail + link-change + env deployments."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import change_request_service


async def _seed(db_session, tenant, user, status="success"):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.deployment import Deployment
    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()
    build = Build(
        tenant_id=tenant.id, subsystem_id=sub.id, git_sha="a"*40,
        build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(build)
    await db_session.flush()
    cr = ChangeRequest(
        tenant_id=tenant.id, title="x", description="y",
        change_type=ChangeType.CODE_DEPLOYMENT, state="created",
        raised_by=user.id,
    )
    db_session.add(cr)
    await db_session.flush()
    dep = Deployment(
        tenant_id=tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=uuid4(),
        deployed_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        status=status,
    )
    db_session.add(dep)
    await db_session.commit()
    return env, build, cr, dep


@pytest.mark.asyncio
async def test_list_and_detail(client, auth_headers, db_session, tenant, user):
    env, build, cr, dep = await _seed(db_session, tenant, user)

    r = await client.get("/api/v1/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())

    r = await client.get(f"/api/v1/deployments/{dep.id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "success"


@pytest.mark.asyncio
async def test_env_deployments(client, auth_headers, db_session, tenant, user):
    env, build, cr, dep = await _seed(db_session, tenant, user)
    r = await client.get(f"/api/v1/environments/{env.id}/deployments", headers=auth_headers)
    assert r.status_code == 200
    assert any(d["id"] == dep.id for d in r.json())


@pytest.mark.asyncio
async def test_link_change_only_replaces_autocreated_crs(client, auth_headers, db_session, tenant, user):
    # The CR we made has the code_deployment type but wasn't created via
    # the Code Deployment lifecycle. The endpoint checks template name.
    env, build, cr_auto, dep = await _seed(db_session, tenant, user)
    from app.db.models.lifecycle import LifecycleTemplate
    from sqlalchemy import select
    tpl = (await db_session.execute(
        select(LifecycleTemplate).where(
            LifecycleTemplate.tenant_id == tenant.id,
            LifecycleTemplate.entity_type == "change_request",
            LifecycleTemplate.name == "Code Deployment",
        )
    )).scalar_one()
    cr_auto.lifecycle_template_id = tpl.id
    await db_session.commit()

    from app.db.models.change_request import ChangeRequest, ChangeType
    cr_human = ChangeRequest(
        tenant_id=tenant.id, title="Human CR", description="",
        change_type=ChangeType.CONFIGURATION, state="draft",
        raised_by=user.id,
    )
    db_session.add(cr_human)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/deployments/{dep.id}/link-change",
        headers=auth_headers,
        json={"change_request_id": cr_human.id},
    )
    assert r.status_code == 200
    assert r.json()["change_request_id"] == cr_human.id
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_deployments_api.py -v
```

Expected: 404.

- [ ] **Step 3: Create the router**

`backend/app/api/v1/deployments.py`:

```python
"""/api/v1/deployments — list, detail, link-change; + env deployments helper."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.base import get_db
from app.db.models.change_request import ChangeRequest
from app.db.models.deployment import Deployment
from app.db.models.lifecycle import LifecycleTemplate
from app.api.v1.schemas.deployment import DeploymentLinkChangeRequest, DeploymentRead


router = APIRouter()
env_sub_router = APIRouter()


@router.get("", response_model=list[DeploymentRead])
async def list_deployments(
    environment_id: Optional[int] = Query(None),
    release_id: Optional[int] = Query(None),
    build_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Deployment).where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.deleted_at.is_(None),
    )
    if environment_id is not None:
        q = q.where(Deployment.environment_id == environment_id)
    if release_id is not None:
        q = q.where(Deployment.release_id == release_id)
    if build_id is not None:
        q = q.where(Deployment.build_id == build_id)
    if status is not None:
        q = q.where(Deployment.status == status)
    if date_from is not None:
        q = q.where(Deployment.deployed_at >= date_from)
    if date_to is not None:
        q = q.where(Deployment.deployed_at <= date_to)
    q = q.order_by(Deployment.deployed_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(q)).scalars().all())


@router.get("/{deployment_id}", response_model=DeploymentRead)
async def get_deployment(
    deployment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    row = (await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.tenant_id == current_user.active_tenant_id,
            Deployment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    return row


@router.post("/{deployment_id}/link-change", response_model=DeploymentRead)
async def link_change(
    deployment_id: int,
    body: DeploymentLinkChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    tenant_id = current_user.active_tenant_id
    dep = (await db.execute(
        select(Deployment).where(
            Deployment.id == deployment_id,
            Deployment.tenant_id == tenant_id,
            Deployment.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")

    # Must currently be linked to a Code Deployment template to be swapped.
    current_tpl = (await db.execute(
        select(LifecycleTemplate).join(
            ChangeRequest, ChangeRequest.lifecycle_template_id == LifecycleTemplate.id,
        ).where(ChangeRequest.id == dep.change_request_id)
    )).scalar_one_or_none()
    if current_tpl is None or current_tpl.name != "Code Deployment":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Deployment is linked to a human-authored change request; cannot swap.",
        )

    new_cr = (await db.execute(
        select(ChangeRequest).where(
            ChangeRequest.id == body.change_request_id,
            ChangeRequest.tenant_id == tenant_id,
            ChangeRequest.deleted_at.is_(None),
        )
    )).scalar_one_or_none()
    if new_cr is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Target change request not found")

    dep.change_request_id = new_cr.id
    await db.flush()
    return dep


@env_sub_router.get("/{environment_id}/deployments", response_model=list[DeploymentRead])
async def list_environment_deployments(
    environment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    q = select(Deployment).where(
        Deployment.tenant_id == current_user.active_tenant_id,
        Deployment.environment_id == environment_id,
        Deployment.deleted_at.is_(None),
    ).order_by(Deployment.deployed_at.desc())
    return list((await db.execute(q)).scalars().all())
```

- [ ] **Step 4: Register**

In `backend/app/main.py`:

```python
from app.api.v1 import deployments as deployments_router

app.include_router(deployments_router.router, prefix="/api/v1/deployments", tags=["deployments"])
app.include_router(deployments_router.env_sub_router, prefix="/api/v1/environments", tags=["deployments"])
```

- [ ] **Step 5: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_deployments_api.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/deployments.py backend/app/main.py backend/tests/integration/test_deployments_api.py
git commit -m "feat(phase-4): /api/v1/deployments list + detail + link-change + env history"
```

---

## Task 18: `EnvironmentSchedule` populates `deployments`

**Files:**
- Modify: `backend/app/services/environment_service.py` — locate `get_environment_schedule` (Phase 2)
- Modify: one existing test file OR create `backend/tests/integration/test_environment_schedule_deployments.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/integration/test_environment_schedule_deployments.py`:

```python
"""/api/v1/environments/{id}/schedule — deployments array populated."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_schedule_includes_deployments(client, auth_headers, db_session, tenant, user):
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.change_request import ChangeRequest, ChangeType
    from app.db.models.deployment import Deployment

    sys = System(tenant_id=tenant.id, name="Orders")
    db_session.add(sys)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys.id, name="orders-api")
    env = Environment(tenant_id=tenant.id, name="sit")
    db_session.add_all([sub, env])
    await db_session.flush()
    build = Build(
        tenant_id=tenant.id, subsystem_id=sub.id, git_sha="a"*40,
        build_number="#1", commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    cr = ChangeRequest(
        tenant_id=tenant.id, title="x", description="y",
        change_type=ChangeType.CODE_DEPLOYMENT, state="deployed",
        raised_by=user.id,
    )
    db_session.add_all([build, cr])
    await db_session.flush()
    dep = Deployment(
        tenant_id=tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=uuid4(),
        deployed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        status="success",
    )
    db_session.add(dep)
    await db_session.commit()

    r = await client.get(
        f"/api/v1/environments/{env.id}/schedule",
        headers=auth_headers,
        params={"date_from": "2026-04-22T00:00:00Z", "date_to": "2026-04-24T00:00:00Z"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(d["id"] == dep.id for d in body["deployments"])
```

- [ ] **Step 2: Run — confirm failure**

```bash
cd backend && uv run pytest tests/integration/test_environment_schedule_deployments.py -v
```

Expected: either `body["deployments"]` is empty, or the schedule endpoint hasn't been extended.

- [ ] **Step 3: Extend the service**

In `backend/app/services/environment_service.py`, find `get_environment_schedule`. In its return dict, replace `"deployments": []` with:

```python
            "deployments": await _get_deployments_for_schedule(
                db, tenant_id, environment_id, date_from, date_to,
            ),
```

And add a helper at the bottom of the file:

```python
async def _get_deployments_for_schedule(
    db, tenant_id: int, environment_id: int, date_from, date_to,
):
    from app.db.models.deployment import Deployment
    from sqlalchemy import select
    q = select(Deployment).where(
        Deployment.tenant_id == tenant_id,
        Deployment.environment_id == environment_id,
        Deployment.deleted_at.is_(None),
        Deployment.deployed_at >= date_from,
        Deployment.deployed_at <= date_to,
    ).order_by(Deployment.deployed_at)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": d.id,
            "build_id": d.build_id,
            "release_id": d.release_id,
            "change_request_id": d.change_request_id,
            "status": d.status,
            "deployed_at": d.deployed_at.isoformat(),
            "deployer_name": d.deployer_name,
        }
        for d in rows
    ]
```

- [ ] **Step 4: Run — confirm pass**

```bash
cd backend && uv run pytest tests/integration/test_environment_schedule_deployments.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_service.py backend/tests/integration/test_environment_schedule_deployments.py
git commit -m "feat(phase-4): EnvironmentSchedule populates deployments array"
```

---

## Task 19: Final verification + mark spec implemented

**Files:**
- Modify: `docs/superpowers/specs/2026-04-23-phase-4-sub1-build-deployment-design.md` — update status

- [ ] **Step 1: Run full backend suite**

```bash
cd backend && uv run pytest -q 2>&1 | tail -10
```

Expected: all tests pass. The new tests add roughly 30 tests on top of the 560 baseline.

- [ ] **Step 2: Run full frontend typecheck (should be untouched)**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Sanity probe the running dev stack**

If a dev stack is running:

```bash
TOKEN="<JWT from login>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/api-keys | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/builds | python3 -m json.tool
```

Expected: `200` with an empty list for each. (The webhook can be exercised end-to-end via the integration test; no need to manually curl it.)

- [ ] **Step 4: Update spec status**

Open `docs/superpowers/specs/2026-04-23-phase-4-sub1-build-deployment-design.md`, replace:

```markdown
**Status:** Draft — awaiting user review
```

with:

```markdown
**Status:** Implemented on `feature/phase-4-sub1-build-deployment` — awaiting MR merge
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-04-23-phase-4-sub1-build-deployment-design.md
git commit -m "docs(spec): mark Phase 4 Sub-1 spec as implemented"
```
