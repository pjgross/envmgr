# Environment Subsystem Configuration, Topology & Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace system-level mock/real status with per-subsystem configuration, add an environment-scoped topology diagram, extend dependency verification to cover component-level deps, and add missing-system detection to the Systems tab.

**Architecture:** New `environment_subsystem` DB table stores per-subsystem `is_mocked` flag, auto-populated when systems are added to an environment. The environment topology reuses the existing ReactFlow + dagre layout from `SystemTopologyDiagram`, with shared components extracted to `src/components/topology/`. Verification extends the existing `verify_environment` service with a second component-dep pass using the new table.

**Tech Stack:** FastAPI + SQLAlchemy async + Alembic (backend); React 18 + TypeScript + MUI + Redux Toolkit + ReactFlow v11 + @dagrejs/dagre (frontend). No test suite exists — verification is done via import compile checks and Swagger smoke tests.

**Spec:** `docs/superpowers/specs/2026-03-24-environment-subsystem-topology-verify-design.md`

---

## File Map

**New files:**
- `backend/app/db/migrations/versions/20260324_1100_<hash>_add_environment_subsystem.py`
- `frontend/src/components/topology/SystemGroupNode.tsx`
- `frontend/src/components/topology/DependencyDetailPane.tsx`
- `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx`

**Modified files:**
- `backend/app/db/models/environment.py` — add `EnvironmentSubSystem`, remove `status`/`mock_notes` from `EnvironmentSystem`, delete `EnvironmentSystemStatus`
- `backend/app/api/v1/schemas/environment.py` — remove status/mock_notes from system schemas, add new subsystem schemas
- `backend/app/api/v1/schemas/dependency.py` — add `ComponentVerifyItem`, extend `VerifyResponse`
- `backend/app/services/environment_system_service.py` — remove status/mock, auto-create/delete subsystem rows, missing-systems logic, new subsystem get/update functions
- `backend/app/services/environment_service.py` — fix verify (remove mock branch, add component pass), fix delete_environment, add get_environment_topology
- `backend/app/api/v1/environments.py` — new subsystem + topology routes
- `frontend/src/types/environment.ts` — remove EnvironmentSystemStatus, add subsystem types
- `frontend/src/types/dependency.ts` — add ComponentVerifyItem, extend VerifyResponse
- `frontend/src/services/environmentService.ts` — add subsystem + topology methods
- `frontend/src/store/environmentSlice.ts` — remove status/mock thunks, add subsystem thunks
- `frontend/src/pages/environments/EnvironmentDetail.tsx` — cleanup + new tabs + all tab content
- `frontend/src/pages/systems/SystemTopologyDiagram.tsx` — update imports after extraction

---

## Task 1: Alembic Migration

**Files:**
- Create: `backend/app/db/migrations/versions/20260324_1100_<hash>_add_environment_subsystem.py`

- [ ] **Step 1: Generate the migration stub**

```bash
cd backend && alembic revision -m "add_environment_subsystem"
```

This creates a file like `20260324_1100_<hash>_add_environment_subsystem.py`. Note the exact filename.

- [ ] **Step 2: Write the DDL manually**

Open the generated file and replace the empty `upgrade`/`downgrade` with:

```python
"""add_environment_subsystem

Revision ID: <hash>
Revises: ff680fa48349
Create Date: 2026-03-24 ...
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '<hash>'
down_revision: Union[str, None] = 'ff680fa48349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "environment_subsystem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("environment_id", sa.Integer(), nullable=False),
        sa.Column("subsystem_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("is_mocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("mock_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["subsystem_id"], ["subsystem.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("environment_id", "subsystem_id", name="uq_env_subsystem"),
    )
    op.create_index("ix_environment_subsystem_environment_id", "environment_subsystem", ["environment_id"])
    op.create_index("ix_environment_subsystem_subsystem_id", "environment_subsystem", ["subsystem_id"])
    op.create_index("ix_environment_subsystem_tenant_id", "environment_subsystem", ["tenant_id"])

    op.drop_column("environment_system", "status")
    op.drop_column("environment_system", "mock_notes")


def downgrade() -> None:
    op.add_column("environment_system", sa.Column("mock_notes", sa.Text(), nullable=True))
    op.add_column("environment_system", sa.Column(
        "status", sa.VARCHAR(length=50), nullable=False, server_default="active"
    ))
    op.drop_index("ix_environment_subsystem_tenant_id", table_name="environment_subsystem")
    op.drop_index("ix_environment_subsystem_subsystem_id", table_name="environment_subsystem")
    op.drop_index("ix_environment_subsystem_environment_id", table_name="environment_subsystem")
    op.drop_table("environment_subsystem")
```

- [ ] **Step 3: Apply the migration**

```bash
cd backend && alembic upgrade head
```

Expected: no errors, ends with `Running upgrade ff680fa48349 -> <hash>, add_environment_subsystem`

- [ ] **Step 4: Verify round-trip**

```bash
cd backend && alembic downgrade -1 && alembic upgrade head
```

Expected: both succeed with no errors.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrations/versions/
git commit -m "feat: add environment_subsystem migration, drop status/mock_notes from environment_system"
```

---

## Task 2: Backend Model Changes

**Files:**
- Modify: `backend/app/db/models/environment.py`

- [ ] **Step 1: Open `backend/app/db/models/environment.py` and make all changes**

The file currently has `EnvironmentSystemStatus` enum and `status`/`mock_notes` on `EnvironmentSystem`. Replace the entire file with:

```python
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, JSON, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EnvironmentStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class Environment(Base):
    """Environment model — a named test environment within a tenant."""

    __tablename__ = "environment"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    environment_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[EnvironmentStatus] = mapped_column(
        SAEnum(EnvironmentStatus, native_enum=False),
        nullable=False,
        default=EnvironmentStatus.ACTIVE,
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    environment_systems: Mapped[list["EnvironmentSystem"]] = relationship(
        "EnvironmentSystem", back_populates="environment", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<Environment(id={self.id}, name='{self.name}', tenant_id={self.tenant_id})>"


class EnvironmentSystem(Base):
    """Junction table linking an Environment to a System."""

    __tablename__ = "environment_system"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    system_id: Mapped[int] = mapped_column(
        ForeignKey("system.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("environment_id", "system_id", name="uq_env_system"),
    )

    environment: Mapped["Environment"] = relationship(
        "Environment", back_populates="environment_systems"
    )
    system: Mapped["System"] = relationship("System")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return f"<EnvironmentSystem(env={self.environment_id}, sys={self.system_id})>"


class EnvironmentSubSystem(Base):
    """Per-subsystem real/mocked configuration for an environment."""

    __tablename__ = "environment_subsystem"

    environment_id: Mapped[int] = mapped_column(
        ForeignKey("environment.id"), nullable=False, index=True
    )
    subsystem_id: Mapped[int] = mapped_column(
        ForeignKey("subsystem.id"), nullable=False, index=True
    )
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenant.id"), nullable=False, index=True)
    is_mocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mock_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("environment_id", "subsystem_id", name="uq_env_subsystem"),
    )

    subsystem: Mapped["SubSystem"] = relationship("SubSystem")  # type: ignore[name-defined]

    def __repr__(self) -> str:
        return (
            f"<EnvironmentSubSystem(env={self.environment_id}, sub={self.subsystem_id}, "
            f"mocked={self.is_mocked})>"
        )
```

- [ ] **Step 2: Verify the model imports cleanly**

```bash
cd backend && uv run python -c "from app.db.models.environment import Environment, EnvironmentSystem, EnvironmentSubSystem; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/db/models/environment.py
git commit -m "feat: add EnvironmentSubSystem model, remove EnvironmentSystemStatus"
```

---

## Task 3: Backend Schema Changes

**Files:**
- Modify: `backend/app/api/v1/schemas/environment.py`
- Modify: `backend/app/api/v1/schemas/dependency.py`

- [ ] **Step 1: Update `backend/app/api/v1/schemas/environment.py`**

Replace entirely with:

```python
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.db.models.environment import EnvironmentStatus
from app.api.v1.schemas.system import SystemResponse


class EnvironmentCreate(BaseModel):
    name: str
    description: Optional[str] = None
    environment_type: str
    status: EnvironmentStatus = EnvironmentStatus.ACTIVE
    custom_fields: Optional[dict] = None


class EnvironmentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    environment_type: Optional[str] = None
    status: Optional[EnvironmentStatus] = None
    custom_fields: Optional[dict] = None


class EnvironmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str] = None
    environment_type: str
    status: EnvironmentStatus
    tenant_id: int
    custom_fields: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


class EnvironmentSystemCreate(BaseModel):
    system_id: int


class EnvironmentSystemUpdate(BaseModel):
    pass  # reserved for future fields


class EnvironmentSystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    system_id: int
    system: SystemResponse


class SystemSummary(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class EnvironmentSystemsResponse(BaseModel):
    """Response for GET /environments/{env_id}/systems — includes missing systems."""
    systems: list[EnvironmentSystemResponse]
    missing_systems: list[SystemSummary]


class VersionSummary(BaseModel):
    build_id: str
    version_label: str
    installed_at: datetime


class EnvironmentSubsystemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    environment_id: int
    subsystem_id: int
    subsystem_name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    system_name: str
    is_mocked: bool
    mock_notes: Optional[str] = None
    latest_version: Optional[VersionSummary] = None


class EnvironmentSubsystemUpdate(BaseModel):
    is_mocked: Optional[bool] = None
    mock_notes: Optional[str] = None


class EnvSubsystemNode(BaseModel):
    """Subsystem node for the environment topology response."""
    id: int
    name: str
    component_type: str
    technology: Optional[str] = None
    system_id: int
    is_mocked: bool
```

- [ ] **Step 2: Update `backend/app/api/v1/schemas/dependency.py` — add `ComponentVerifyItem` and extend `VerifyResponse`**

Add these two classes after `SystemVerifyResult` (around line 154):

```python
class ComponentVerifyItem(BaseModel):
    from_subsystem_id: int
    from_subsystem_name: str
    to_subsystem_id: int
    to_subsystem_name: str
    dependency_type: DependencyType
    status: Literal["satisfied", "mocked", "missing"]
```

Then update `VerifyResponse` to:

```python
class VerifyResponse(BaseModel):
    environment_id: int
    total_dependencies: int
    satisfied_count: int
    mocked_count: int
    missing_count: int
    systems: list[SystemVerifyResult]
    component_total: int = 0
    component_satisfied: int = 0
    component_mocked: int = 0
    component_missing: int = 0
    component_dependencies: list[ComponentVerifyItem] = []
```

- [ ] **Step 3: Verify schemas compile**

```bash
cd backend && uv run python -c "from app.api.v1.schemas.environment import EnvironmentSubsystemResponse, EnvironmentSystemsResponse; from app.api.v1.schemas.dependency import VerifyResponse, ComponentVerifyItem; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/schemas/environment.py backend/app/api/v1/schemas/dependency.py
git commit -m "feat: update environment and dependency schemas for subsystem mock config"
```

---

## Task 4: Backend environment_system_service.py

**Files:**
- Modify: `backend/app/services/environment_system_service.py`

This task rewrites `environment_system_service.py` to: remove status/mock handling, auto-create/delete `EnvironmentSubSystem` rows, compute missing systems, and add the new subsystem get/update functions.

- [ ] **Step 1: Replace `backend/app/services/environment_system_service.py`**

```python
from fastapi import HTTPException, status
from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models.environment import EnvironmentSystem, EnvironmentSubSystem
from app.db.models.system import System, SubSystem
from app.db.models.dependency import SystemDependency
from app.db.models.version import EnvironmentSubSystemVersion
from app.services.environment_service import get_environment
from app.api.v1.schemas.environment import (
    EnvironmentSystemCreate,
    EnvironmentSystemUpdate,
    EnvironmentSystemsResponse,
    EnvironmentSystemResponse,
    SystemSummary,
    EnvironmentSubsystemResponse,
    EnvironmentSubsystemUpdate,
    VersionSummary,
)


async def list_systems_in_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> EnvironmentSystemsResponse:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSystem)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys_rows = list(result.scalars().all())
    assigned_system_ids = {row.system_id for row in env_sys_rows}

    # Compute missing systems: system-dep targets not in environment
    missing_systems: list[SystemSummary] = []
    if assigned_system_ids:
        deps_result = await db.execute(
            select(SystemDependency)
            .where(
                SystemDependency.from_system_id.in_(assigned_system_ids),
                SystemDependency.tenant_id == tenant_id,
            )
            .options(selectinload(SystemDependency.to_system))
        )
        seen_missing: set[int] = set()
        for dep in deps_result.scalars().all():
            to_id = dep.to_system_id
            if to_id not in assigned_system_ids and to_id not in seen_missing:
                seen_missing.add(to_id)
                if dep.to_system:
                    missing_systems.append(
                        SystemSummary(
                            id=dep.to_system.id,
                            name=dep.to_system.name,
                            description=dep.to_system.description,
                        )
                    )

    systems = [
        EnvironmentSystemResponse(
            id=row.id,
            environment_id=row.environment_id,
            system_id=row.system_id,
            system=row.system,
        )
        for row in env_sys_rows
    ]
    return EnvironmentSystemsResponse(systems=systems, missing_systems=missing_systems)


async def add_system_to_environment(
    db: AsyncSession,
    env_id: int,
    data: EnvironmentSystemCreate,
    tenant_id: int,
) -> EnvironmentSystem:
    await get_environment(db, env_id, tenant_id)

    sys_result = await db.execute(
        select(System).where(
            System.id == data.system_id,
            System.tenant_id == tenant_id,
            System.deleted_at.is_(None),
        )
    )
    if sys_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="System not found")

    existing = await db.execute(
        select(EnvironmentSystem).where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == data.system_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="System is already assigned to this environment",
        )

    env_sys = EnvironmentSystem(
        environment_id=env_id,
        system_id=data.system_id,
        tenant_id=tenant_id,
    )
    db.add(env_sys)
    await db.flush()

    # Auto-create EnvironmentSubSystem rows for each subsystem
    subs_result = await db.execute(
        select(SubSystem).where(
            SubSystem.system_id == data.system_id,
            SubSystem.tenant_id == tenant_id,
            SubSystem.deleted_at.is_(None),
        )
    )
    subsystems = list(subs_result.scalars().all())
    if subsystems:
        stmt = pg_insert(EnvironmentSubSystem).values([
            {
                "environment_id": env_id,
                "subsystem_id": sub.id,
                "tenant_id": tenant_id,
                "is_mocked": False,
            }
            for sub in subsystems
        ]).on_conflict_do_nothing(index_elements=["environment_id", "subsystem_id"])
        await db.execute(stmt)

    await db.refresh(env_sys, ["system"])
    return env_sys


async def _get_env_system(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> EnvironmentSystem:
    await get_environment(db, env_id, tenant_id)
    result = await db.execute(
        select(EnvironmentSystem)
        .where(
            EnvironmentSystem.environment_id == env_id,
            EnvironmentSystem.system_id == system_id,
            EnvironmentSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys = result.scalar_one_or_none()
    if env_sys is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System not found in this environment",
        )
    return env_sys


async def update_system_in_environment(
    db: AsyncSession,
    env_id: int,
    system_id: int,
    data: EnvironmentSystemUpdate,
    tenant_id: int,
) -> EnvironmentSystem:
    """No-op update kept for route compatibility. Returns current row."""
    return await _get_env_system(db, env_id, system_id, tenant_id)


async def remove_system_from_environment(
    db: AsyncSession, env_id: int, system_id: int, tenant_id: int
) -> None:
    env_sys = await _get_env_system(db, env_id, system_id, tenant_id)

    # Clean up EnvironmentSubSystem rows for this system's subsystems
    subs_result = await db.execute(
        select(SubSystem.id).where(
            SubSystem.system_id == system_id,
            SubSystem.tenant_id == tenant_id,
        )
    )
    subsystem_ids = [row[0] for row in subs_result.all()]
    if subsystem_ids:
        await db.execute(
            delete(EnvironmentSubSystem).where(
                EnvironmentSubSystem.environment_id == env_id,
                EnvironmentSubSystem.subsystem_id.in_(subsystem_ids),
            )
        )

    await db.delete(env_sys)
    await db.flush()


# ---------------------------------------------------------------------------
# EnvironmentSubSystem operations
# ---------------------------------------------------------------------------


async def get_environment_subsystems(
    db: AsyncSession, env_id: int, tenant_id: int
) -> list[EnvironmentSubsystemResponse]:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystem)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSubSystem.subsystem))
    )
    rows = list(result.scalars().all())

    # Collect subsystem IDs to batch-load system names and latest versions
    subsystem_ids = [row.subsystem_id for row in rows]
    if not subsystem_ids:
        return []

    # Batch load system names via the subsystem→system relationship
    subsystem_result = await db.execute(
        select(SubSystem)
        .where(SubSystem.id.in_(subsystem_ids))
        .options(selectinload(SubSystem.system))
    )
    subsystem_map = {sub.id: sub for sub in subsystem_result.scalars().all()}

    # Batch load latest version per subsystem
    # Use a subquery: for each subsystem_id, get the most recent installed_at row
    from sqlalchemy import func
    latest_version_subq = (
        select(
            EnvironmentSubSystemVersion.subsystem_id,
            func.max(EnvironmentSubSystemVersion.installed_at).label("max_installed"),
        )
        .where(
            EnvironmentSubSystemVersion.environment_id == env_id,
            EnvironmentSubSystemVersion.subsystem_id.in_(subsystem_ids),
        )
        .group_by(EnvironmentSubSystemVersion.subsystem_id)
        .subquery()
    )
    versions_result = await db.execute(
        select(EnvironmentSubSystemVersion).join(
            latest_version_subq,
            (EnvironmentSubSystemVersion.subsystem_id == latest_version_subq.c.subsystem_id)
            & (EnvironmentSubSystemVersion.installed_at == latest_version_subq.c.max_installed),
        ).where(EnvironmentSubSystemVersion.environment_id == env_id)
    )
    version_map: dict[int, EnvironmentSubSystemVersion] = {
        v.subsystem_id: v for v in versions_result.scalars().all()
    }

    out = []
    for row in rows:
        sub = subsystem_map.get(row.subsystem_id)
        if sub is None:
            continue
        ver = version_map.get(row.subsystem_id)
        out.append(
            EnvironmentSubsystemResponse(
                id=row.id,
                environment_id=row.environment_id,
                subsystem_id=row.subsystem_id,
                subsystem_name=sub.name,
                component_type=sub.component_type,
                technology=sub.technology,
                system_id=sub.system_id,
                system_name=sub.system.name if sub.system else f"System#{sub.system_id}",
                is_mocked=row.is_mocked,
                mock_notes=row.mock_notes,
                latest_version=VersionSummary(
                    build_id=ver.build_id,
                    version_label=ver.version_label,
                    installed_at=ver.installed_at,
                ) if ver else None,
            )
        )
    return out


async def update_environment_subsystem(
    db: AsyncSession,
    env_id: int,
    subsystem_id: int,
    data: EnvironmentSubsystemUpdate,
    tenant_id: int,
) -> EnvironmentSubsystemResponse:
    await get_environment(db, env_id, tenant_id)

    result = await db.execute(
        select(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.subsystem_id == subsystem_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Subsystem not found in this environment",
        )

    if data.is_mocked is not None:
        row.is_mocked = data.is_mocked
    if data.mock_notes is not None:
        row.mock_notes = data.mock_notes

    await db.flush()

    # Return full response (re-use get function)
    subs = await get_environment_subsystems(db, env_id, tenant_id)
    match = next((s for s in subs if s.subsystem_id == subsystem_id), None)
    if match is None:
        raise HTTPException(status_code=500, detail="Failed to reload subsystem")
    return match
```

- [ ] **Step 2: Check imports compile**

```bash
cd backend && uv run python -c "from app.services.environment_system_service import list_systems_in_environment, add_system_to_environment, get_environment_subsystems; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/environment_system_service.py
git commit -m "feat: rewrite environment_system_service — per-subsystem mock config, missing systems"
```

---

## Task 5: Backend environment_service.py — verify + delete + topology

**Files:**
- Modify: `backend/app/services/environment_service.py`

- [ ] **Step 1: Update `verify_environment` in `backend/app/services/environment_service.py`**

Find the `verify_environment` function (starts around line 154). Replace the entire function with:

```python
async def verify_environment(db: AsyncSession, env_id: int, tenant_id: int) -> dict:
    """Check system-level and component-level dependency coverage for an environment."""
    await get_environment(db, env_id, tenant_id)

    # Load assigned systems
    env_sys_result = await db.execute(
        select(EnvironmentSystem)
        .where(EnvironmentSystem.environment_id == env_id)
        .options(selectinload(EnvironmentSystem.system))
    )
    env_sys_rows = list(env_sys_result.scalars().all())
    env_system_map: dict[int, EnvironmentSystem] = {row.system_id: row for row in env_sys_rows}
    system_ids = list(env_system_map.keys())

    # ------------------------------------------------------------------ #
    # System-level pass (satisfied / missing only — no more "mocked")     #
    # ------------------------------------------------------------------ #
    deps_result = await db.execute(
        select(SystemDependency)
        .where(
            SystemDependency.from_system_id.in_(system_ids),
            SystemDependency.tenant_id == tenant_id,
        )
        .options(selectinload(SystemDependency.to_system))
    )
    all_deps = list(deps_result.scalars().all())

    deps_by_system: dict[int, list[SystemDependency]] = defaultdict(list)
    for dep in all_deps:
        deps_by_system[dep.from_system_id].append(dep)

    systems_result: list[dict] = []
    total_deps = satisfied_count = mocked_count = missing_count = 0

    for system_id, env_sys in env_system_map.items():
        verify_items: list[dict] = []
        for dep in deps_by_system[system_id]:
            to_id = dep.to_system_id
            if to_id in env_system_map:
                dep_status = "satisfied"
                satisfied_count += 1
            else:
                dep_status = "missing"
                missing_count += 1
            total_deps += 1
            to_system_name = dep.to_system.name if dep.to_system else f"System#{to_id}"
            verify_items.append({
                "to_system_id": to_id,
                "to_system_name": to_system_name,
                "dependency_type": dep.dependency_type,
                "status": dep_status,
            })
        systems_result.append({
            "system_id": system_id,
            "system_name": env_sys.system.name,
            "dependencies": verify_items,
        })

    # ------------------------------------------------------------------ #
    # Component-level pass                                                 #
    # ------------------------------------------------------------------ #
    comp_total = comp_satisfied = comp_mocked = comp_missing = 0
    comp_dep_items: list[dict] = []

    if system_ids:
        # Load all env subsystem mock status
        env_sub_result = await db.execute(
            select(EnvironmentSubSystem).where(
                EnvironmentSubSystem.environment_id == env_id,
                EnvironmentSubSystem.tenant_id == tenant_id,
            )
        )
        env_sub_map: dict[int, bool] = {
            row.subsystem_id: row.is_mocked for row in env_sub_result.scalars().all()
        }

        # Load subsystem IDs belonging to assigned systems
        env_subsystem_ids_result = await db.execute(
            select(SubSystem.id, SubSystem.name).where(
                SubSystem.system_id.in_(system_ids),
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        env_subsystem_id_to_name = {row[0]: row[1] for row in env_subsystem_ids_result.all()}
        env_subsystem_ids = list(env_subsystem_id_to_name.keys())

        if env_subsystem_ids:
            comp_deps_result = await db.execute(
                select(ComponentDependency)
                .where(
                    ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.tenant_id == tenant_id,
                )
                .options(
                    selectinload(ComponentDependency.from_subsystem),
                    selectinload(ComponentDependency.to_subsystem),
                )
            )
            # Load all subsystem names needed for to_subsystem
            all_comp_deps = list(comp_deps_result.scalars().all())
            for dep in all_comp_deps:
                to_id = dep.to_subsystem_id
                from_name = dep.from_subsystem.name if dep.from_subsystem else f"SubSystem#{dep.from_subsystem_id}"
                to_name = dep.to_subsystem.name if dep.to_subsystem else f"SubSystem#{to_id}"

                if to_id in env_sub_map:
                    is_mocked = env_sub_map[to_id]
                    dep_status = "mocked" if is_mocked else "satisfied"
                    if is_mocked:
                        comp_mocked += 1
                    else:
                        comp_satisfied += 1
                else:
                    dep_status = "missing"
                    comp_missing += 1

                comp_total += 1
                comp_dep_items.append({
                    "from_subsystem_id": dep.from_subsystem_id,
                    "from_subsystem_name": from_name,
                    "to_subsystem_id": to_id,
                    "to_subsystem_name": to_name,
                    "dependency_type": dep.dependency_type,
                    "status": dep_status,
                })

    return {
        "environment_id": env_id,
        "total_dependencies": total_deps,
        "satisfied_count": satisfied_count,
        "mocked_count": mocked_count,
        "missing_count": missing_count,
        "systems": systems_result,
        "component_total": comp_total,
        "component_satisfied": comp_satisfied,
        "component_mocked": comp_mocked,
        "component_missing": comp_missing,
        "component_dependencies": comp_dep_items,
    }
```

- [ ] **Step 2: Update `delete_environment` in `environment_service.py`**

Find the `delete_environment` function. Add the `EnvironmentSubSystem` cleanup before the soft-delete line:

```python
async def delete_environment(
    db: AsyncSession, env_id: int, tenant_id: int
) -> None:
    env = await get_environment(db, env_id, tenant_id)

    # Hard-delete all environment_subsystem junction rows
    await db.execute(
        delete(EnvironmentSubSystem).where(
            EnvironmentSubSystem.environment_id == env_id
        )
    )

    env.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await publish_event(
        db,
        event_type="EnvironmentDeleted",
        aggregate_id=env.id,
        aggregate_type="Environment",
        payload={"id": env.id, "name": env.name, "tenant_id": env.tenant_id},
        tenant_id=env.tenant_id,
    )
```

Add `from sqlalchemy import delete` to imports at the top if not already present, and `from app.db.models.environment import EnvironmentSubSystem`.

- [ ] **Step 3: Add `get_environment_topology` to `environment_service.py`**

Add at the bottom of the file:

```python
async def get_environment_topology(db: AsyncSession, env_id: int, tenant_id: int) -> dict:
    """Return all subsystems in the env + component deps for the topology diagram."""
    await get_environment(db, env_id, tenant_id)

    # Load env subsystems with mock status
    env_sub_result = await db.execute(
        select(EnvironmentSubSystem)
        .where(
            EnvironmentSubSystem.environment_id == env_id,
            EnvironmentSubSystem.tenant_id == tenant_id,
        )
        .options(selectinload(EnvironmentSubSystem.subsystem))
    )
    env_sub_rows = list(env_sub_result.scalars().all())

    if not env_sub_rows:
        return {
            "environment_id": env_id,
            "subsystems": [],
            "dependencies": [],
            "system_names": {},
            "outside_subsystems": [],
            "outside_dependencies": [],
        }

    env_subsystem_ids = [row.subsystem_id for row in env_sub_rows]
    env_subsystem_id_set = set(env_subsystem_ids)
    is_mocked_map = {row.subsystem_id: row.is_mocked for row in env_sub_rows}

    # Collect system IDs and names
    subsystem_to_system: dict[int, int] = {}
    for row in env_sub_rows:
        if row.subsystem:
            subsystem_to_system[row.subsystem_id] = row.subsystem.system_id

    system_ids = list({v for v in subsystem_to_system.values()})
    sys_result = await db.execute(
        select(System).where(System.id.in_(system_ids), System.tenant_id == tenant_id)
    )
    system_names: dict[int, str] = {s.id: s.name for s in sys_result.scalars().all()}

    # Internal deps (both endpoints in env)
    internal_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
            ComponentDependency.to_subsystem_id.in_(env_subsystem_ids),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    internal_deps = list(internal_result.scalars().all())

    # Cross-env deps (exactly one endpoint in env)
    cross_result = await db.execute(
        select(ComponentDependency)
        .where(
            ComponentDependency.tenant_id == tenant_id,
            or_(
                and_(
                    ComponentDependency.from_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.to_subsystem_id.notin_(env_subsystem_ids),
                ),
                and_(
                    ComponentDependency.to_subsystem_id.in_(env_subsystem_ids),
                    ComponentDependency.from_subsystem_id.notin_(env_subsystem_ids),
                ),
            ),
        )
        .options(
            selectinload(ComponentDependency.from_subsystem),
            selectinload(ComponentDependency.to_subsystem),
            selectinload(ComponentDependency.endpoints),
        )
    )
    cross_deps = list(cross_result.scalars().all())

    # Collect outside subsystem IDs
    outside_sub_ids: set[int] = set()
    for dep in cross_deps:
        if dep.from_subsystem_id not in env_subsystem_id_set:
            outside_sub_ids.add(dep.from_subsystem_id)
        if dep.to_subsystem_id not in env_subsystem_id_set:
            outside_sub_ids.add(dep.to_subsystem_id)

    outside_subsystems: list[SubSystem] = []
    if outside_sub_ids:
        out_result = await db.execute(
            select(SubSystem).where(
                SubSystem.id.in_(outside_sub_ids),
                SubSystem.tenant_id == tenant_id,
                SubSystem.deleted_at.is_(None),
            )
        )
        outside_subsystems = list(out_result.scalars().all())

    found_outside_ids = {s.id for s in outside_subsystems}
    cross_deps = [
        d for d in cross_deps
        if (d.from_subsystem_id in env_subsystem_id_set or d.from_subsystem_id in found_outside_ids)
        and (d.to_subsystem_id in env_subsystem_id_set or d.to_subsystem_id in found_outside_ids)
    ]

    # Resolve system names for outside systems
    outside_system_ids = {s.system_id for s in outside_subsystems} - set(system_ids)
    if outside_system_ids:
        out_sys_result = await db.execute(
            select(System).where(System.id.in_(outside_system_ids), System.tenant_id == tenant_id)
        )
        for sys in out_sys_result.scalars().all():
            system_names[sys.id] = sys.name

    # Build subsystem nodes
    subsystem_nodes = []
    for row in env_sub_rows:
        sub = row.subsystem
        if sub is None:
            continue
        subsystem_nodes.append({
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": row.is_mocked,
        })

    outside_sub_nodes = [
        {
            "id": sub.id,
            "name": sub.name,
            "component_type": sub.component_type,
            "technology": sub.technology,
            "system_id": sub.system_id,
            "is_mocked": False,
        }
        for sub in outside_subsystems
    ]

    return {
        "environment_id": env_id,
        "subsystems": subsystem_nodes,
        "dependencies": internal_deps,
        "system_names": {str(k): v for k, v in system_names.items()},
        "outside_subsystems": outside_sub_nodes,
        "outside_dependencies": cross_deps,
    }
```

Add the needed imports at the top of `environment_service.py` if not already present:
```python
from sqlalchemy import delete, or_, and_
from app.db.models.environment import EnvironmentSubSystem
from app.db.models.system import SubSystem, System
from app.db.models.dependency import SystemDependency, ComponentDependency
```

- [ ] **Step 4: Verify imports compile**

```bash
cd backend && uv run python -c "from app.services.environment_service import verify_environment, delete_environment, get_environment_topology; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/environment_service.py
git commit -m "feat: extend verify_environment with component pass, add topology service, fix delete cleanup"
```

---

## Task 6: Backend API Routes

**Files:**
- Modify: `backend/app/api/v1/environments.py`

- [ ] **Step 1: Update imports in `environments.py`**

Replace the imports at the top with:

```python
from typing import Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db
from app.core.security import get_current_user, require_tenant_admin
from app.db.models.environment import EnvironmentStatus
from app.services import environment_service, environment_system_service
from app.services import version_service
from app.api.v1.schemas.environment import (
    EnvironmentCreate,
    EnvironmentUpdate,
    EnvironmentResponse,
    EnvironmentSystemCreate,
    EnvironmentSystemUpdate,
    EnvironmentSystemResponse,
    EnvironmentSystemsResponse,
    EnvironmentSubsystemResponse,
    EnvironmentSubsystemUpdate,
)
from app.api.v1.schemas.dependency import VerifyResponse
from app.api.v1.schemas.version import VersionCreate, VersionUpdate, VersionResponse
```

- [ ] **Step 2: Update `list_systems_in_environment` route response model**

Change the route from `list[EnvironmentSystemResponse]` to `EnvironmentSystemsResponse`:

```python
@router.get("/{env_id}/systems", response_model=EnvironmentSystemsResponse)
async def list_systems_in_environment(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_system_service.list_systems_in_environment(
        db, env_id, current_user.active_tenant_id
    )
```

- [ ] **Step 3: Add new subsystem and topology routes**

After the `remove_system_from_environment` route, add:

```python
# ---------------------------------------------------------------------------
# EnvironmentSubSystem endpoints
# ---------------------------------------------------------------------------


@router.get("/{env_id}/subsystems", response_model=list[EnvironmentSubsystemResponse])
async def list_environment_subsystems(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_system_service.get_environment_subsystems(
        db, env_id, current_user.active_tenant_id
    )


@router.patch("/{env_id}/subsystems/{subsystem_id}", response_model=EnvironmentSubsystemResponse)
async def update_environment_subsystem(
    env_id: int,
    subsystem_id: int,
    data: EnvironmentSubsystemUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_tenant_admin()),
):
    return await environment_system_service.update_environment_subsystem(
        db, env_id, subsystem_id, data, current_user.active_tenant_id
    )


# ---------------------------------------------------------------------------
# Environment Topology
# ---------------------------------------------------------------------------


@router.get("/{env_id}/topology")
async def get_environment_topology(
    env_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await environment_service.get_environment_topology(
        db, env_id, current_user.active_tenant_id
    )
```

- [ ] **Step 4: Full import compile check**

```bash
cd backend && uv run python -c "from app.api.v1.environments import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Start the server and do a quick smoke test**

```bash
cd backend && uvicorn app.main:app --reload
```

Then in a browser: `http://localhost:8000/docs`
- Verify `GET /environments/{env_id}/subsystems` appears
- Verify `PATCH /environments/{env_id}/subsystems/{subsystem_id}` appears
- Verify `GET /environments/{env_id}/topology` appears
- Verify `GET /environments/{env_id}/systems` response model changed

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/v1/environments.py
git commit -m "feat: add subsystem and topology routes to environments API"
```

---

## Task 7: Frontend Types

**Files:**
- Modify: `frontend/src/types/environment.ts`
- Modify: `frontend/src/types/dependency.ts`

- [ ] **Step 1: Replace `frontend/src/types/environment.ts`**

```typescript
export type EnvironmentStatus = 'active' | 'inactive' | 'maintenance' | 'decommissioned';

export interface EnvironmentResponse {
  id: number;
  name: string;
  description: string | null;
  environment_type: string;
  status: EnvironmentStatus;
  tenant_id: number;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SystemSummary {
  id: number;
  name: string;
  description: string | null;
}

export interface EnvironmentSystemResponse {
  id: number;
  environment_id: number;
  system_id: number;
  system: {
    id: number;
    name: string;
    description: string | null;
    github_repository_url: string | null;
  };
}

export interface EnvironmentSystemsResponse {
  systems: EnvironmentSystemResponse[];
  missing_systems: SystemSummary[];
}

export interface EnvironmentCreate {
  name: string;
  description?: string;
  environment_type: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentUpdate {
  name?: string;
  description?: string;
  environment_type?: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentSystemCreate {
  system_id: number;
}

export interface EnvironmentSystemUpdate {
  // reserved for future fields
}

export interface VersionSummary {
  build_id: string;
  version_label: string;
  installed_at: string;
}

export interface EnvironmentSubsystemResponse {
  id: number;
  environment_id: number;
  subsystem_id: number;
  subsystem_name: string;
  component_type: string;
  technology: string | null;
  system_id: number;
  system_name: string;
  is_mocked: boolean;
  mock_notes: string | null;
  latest_version: VersionSummary | null;
}

export interface EnvironmentSubsystemUpdate {
  is_mocked?: boolean;
  mock_notes?: string | null;
}

export interface EnvSubsystemNode {
  id: number;
  name: string;
  component_type: string;
  technology: string | null;
  system_id: number;
  is_mocked: boolean;
}
```

- [ ] **Step 2: Update `frontend/src/types/dependency.ts`**

Add `ComponentVerifyItem` interface and extend `VerifyResponse`:

```typescript
export interface ComponentVerifyItem {
  from_subsystem_id: number;
  from_subsystem_name: string;
  to_subsystem_id: number;
  to_subsystem_name: string;
  dependency_type: DependencyType;
  status: 'satisfied' | 'mocked' | 'missing';
}
```

Update `VerifyResponse` to add:
```typescript
  component_total: number;
  component_satisfied: number;
  component_mocked: number;
  component_missing: number;
  component_dependencies: ComponentVerifyItem[];
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors before proceeding.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/environment.ts frontend/src/types/dependency.ts
git commit -m "feat: update frontend types for subsystem mock config and verify extension"
```

---

## Task 8: Frontend Service + Redux

**Files:**
- Modify: `frontend/src/services/environmentService.ts`
- Modify: `frontend/src/store/environmentSlice.ts`

- [ ] **Step 1: Replace `frontend/src/services/environmentService.ts`**

```typescript
import api from './api';
import type {
  EnvironmentResponse,
  EnvironmentSystemResponse,
  EnvironmentSystemsResponse,
  EnvironmentSubsystemResponse,
  EnvironmentSubsystemUpdate,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
} from '../types/environment';

export const environmentService = {
  listEnvironments: (params?: { status?: string; environment_type?: string }): Promise<EnvironmentResponse[]> =>
    api.get('/environments/', { params }).then((r) => r.data),

  getEnvironment: (id: number): Promise<EnvironmentResponse> =>
    api.get(`/environments/${id}`).then((r) => r.data),

  createEnvironment: (data: EnvironmentCreate): Promise<EnvironmentResponse> =>
    api.post('/environments/', data).then((r) => r.data),

  updateEnvironment: (id: number, data: EnvironmentUpdate): Promise<EnvironmentResponse> =>
    api.patch(`/environments/${id}`, data).then((r) => r.data),

  deleteEnvironment: (id: number): Promise<void> =>
    api.delete(`/environments/${id}`).then((r) => r.data),

  listSystemsInEnvironment: (envId: number): Promise<EnvironmentSystemsResponse> =>
    api.get(`/environments/${envId}/systems`).then((r) => r.data),

  addSystemToEnvironment: (envId: number, data: EnvironmentSystemCreate): Promise<EnvironmentSystemResponse> =>
    api.post(`/environments/${envId}/systems`, data).then((r) => r.data),

  updateSystemInEnvironment: (
    envId: number,
    systemId: number,
    data: EnvironmentSystemUpdate
  ): Promise<EnvironmentSystemResponse> =>
    api.patch(`/environments/${envId}/systems/${systemId}`, data).then((r) => r.data),

  removeSystemFromEnvironment: (envId: number, systemId: number): Promise<void> =>
    api.delete(`/environments/${envId}/systems/${systemId}`).then((r) => r.data),

  listEnvironmentSubsystems: (envId: number): Promise<EnvironmentSubsystemResponse[]> =>
    api.get(`/environments/${envId}/subsystems`).then((r) => r.data),

  updateEnvironmentSubsystem: (
    envId: number,
    subsystemId: number,
    data: EnvironmentSubsystemUpdate
  ): Promise<EnvironmentSubsystemResponse> =>
    api.patch(`/environments/${envId}/subsystems/${subsystemId}`, data).then((r) => r.data),

  getEnvironmentTopology: (envId: number): Promise<unknown> =>
    api.get(`/environments/${envId}/topology`).then((r) => r.data),
};
```

- [ ] **Step 2: Update `frontend/src/store/environmentSlice.ts`**

Key changes:
- Update `EnvironmentState` to use `EnvironmentSystemsResponse` for the systems list and add `envSubsystems`
- Remove `EnvironmentSystemUpdate`/`status`/`mock_notes` from `updateSystemInEnvironment` thunk
- Add `fetchEnvSubsystems` and `updateEnvSubsystem` thunks

Update the state interface:
```typescript
import type {
  EnvironmentResponse,
  EnvironmentSystemResponse,
  EnvironmentSystemsResponse,
  EnvironmentSubsystemResponse,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
  EnvironmentSubsystemUpdate,
} from '../types/environment';

interface EnvironmentState {
  environments: EnvironmentResponse[];
  currentEnvironment: EnvironmentResponse | null;
  environmentSystemsData: EnvironmentSystemsResponse;
  envSubsystems: EnvironmentSubsystemResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentState = {
  environments: [],
  currentEnvironment: null,
  environmentSystemsData: { systems: [], missing_systems: [] },
  envSubsystems: [],
  loading: false,
  error: null,
};
```

Update `fetchEnvironmentSystems` to reflect new return type:
```typescript
export const fetchEnvironmentSystems = createAsyncThunk(
  'environment/fetchEnvironmentSystems',
  (envId: number) => environmentService.listSystemsInEnvironment(envId)
);
```

Add new thunks:
```typescript
export const fetchEnvSubsystems = createAsyncThunk(
  'environment/fetchEnvSubsystems',
  (envId: number) => environmentService.listEnvironmentSubsystems(envId)
);

export const updateEnvSubsystem = createAsyncThunk(
  'environment/updateEnvSubsystem',
  ({ envId, subsystemId, data }: { envId: number; subsystemId: number; data: EnvironmentSubsystemUpdate }) =>
    environmentService.updateEnvironmentSubsystem(envId, subsystemId, data)
);
```

Update the slice reducers for `fetchEnvironmentSystems` to store `environmentSystemsData`:
```typescript
.addCase(fetchEnvironmentSystems.fulfilled, (state, action) => {
  state.environmentSystemsData = action.payload;
  state.loading = false;
})
```

Add reducers for the new thunks:
```typescript
// fetchEnvSubsystems
.addCase(fetchEnvSubsystems.pending, (state) => { state.loading = true; state.error = null; })
.addCase(fetchEnvSubsystems.fulfilled, (state, action) => {
  state.envSubsystems = action.payload;
  state.loading = false;
})
.addCase(fetchEnvSubsystems.rejected, (state, action) => {
  state.loading = false;
  state.error = action.error.message ?? 'Failed to fetch subsystems';
})
// updateEnvSubsystem
.addCase(updateEnvSubsystem.fulfilled, (state, action) => {
  const idx = state.envSubsystems.findIndex((s) => s.subsystem_id === action.payload.subsystem_id);
  if (idx !== -1) state.envSubsystems[idx] = action.payload;
})
```

Also update `addSystemToEnvironment.fulfilled` to push to `environmentSystemsData.systems`:
```typescript
.addCase(addSystemToEnvironment.fulfilled, (state, action) => {
  state.environmentSystemsData.systems.push(action.payload);
  state.loading = false;
})
```

And `removeSystemFromEnvironment.fulfilled`:
```typescript
.addCase(removeSystemFromEnvironment.fulfilled, (state, action) => {
  state.environmentSystemsData.systems = state.environmentSystemsData.systems.filter(
    (s) => s.system_id !== action.payload.systemId
  );
  state.loading = false;
})
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/services/environmentService.ts frontend/src/store/environmentSlice.ts
git commit -m "feat: update environment service and Redux slice for subsystem mock config"
```

---

## Task 9: EnvironmentDetail Cleanup + Systems Tab

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

This is a large change. Work through it in three sub-steps.

- [ ] **Step 1: Remove all EnvironmentSystemStatus references and update imports**

In `EnvironmentDetail.tsx`:
- Remove `EnvironmentSystemStatus` from the import list on line 62
- Delete the `ENV_SYS_STATUS_COLORS` constant (lines 74-78)
- Remove `status` from `SysFormValues` interface and `emptySysForm`
- Remove `status: EnvironmentSystemStatus` from all usages in form state and dialog
- Update the `useSelector` for `environmentSystems` to use the new shape:
  ```typescript
  const { environmentSystemsData, loading, error } = useSelector(...)
  const environmentSystems = environmentSystemsData.systems
  const missingSystems = environmentSystemsData.missing_systems
  ```
- Remove `status` and `mock_notes` from `EnvironmentSystemCreate` / `EnvironmentSystemUpdate` usage in `handleSysSave`
- Remove `updateSystemInEnvironment` import and usage (the edit system dialog now only has the system selector — no status or mock notes)

- [ ] **Step 2: Update tab structure**

Change tabs from `Overview | Systems | Versions` to `Overview | Systems | Components | Topology`:

```tsx
<Tabs value={tab} onChange={handleTabChange} sx={{ mb: 2 }}>
  <Tab label="Overview" />
  <Tab label="Systems" />
  <Tab label="Components" />
  <Tab label="Topology" />
</Tabs>
```

Update `handleTabChange` to lazy-load subsystems when tab 2 (Components) is opened:
```typescript
const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
  setTab(newValue);
  if (newValue === 2) {
    dispatch(fetchEnvSubsystems(envId));
  }
};
```

Remove the old Versions tab lazy-load logic (the `versionCurrentOnly` and version fetch on tab 2).

- [ ] **Step 3: Update Systems tab (tab === 1)**

Replace the Systems tab render with:

```tsx
{tab === 1 && (
  <Box>
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
      <Button variant="contained" startIcon={<AddIcon />} onClick={openSysCreate}>
        Add System
      </Button>
    </Box>

    <TableContainer component={Paper}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>System</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {environmentSystems.map((envSys) => (
            <TableRow key={envSys.id} hover>
              <TableCell>
                <Typography variant="body2" fontWeight="medium">
                  {envSys.system.name}
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Tooltip title="Remove">
                  <IconButton
                    size="small"
                    color="error"
                    onClick={() => setSysDeleteTarget(envSys)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {missingSystems.map((sys) => (
            <TableRow key={`missing-${sys.id}`} sx={{ opacity: 0.5 }}>
              <TableCell>
                <Typography variant="body2">{sys.name}</Typography>
                <Typography variant="caption" color="text.secondary">
                  Required by a dependency — not yet in environment
                </Typography>
              </TableCell>
              <TableCell align="right">
                <Tooltip title="Add to environment">
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<AddIcon />}
                    onClick={() => {
                      setSysEditTarget(null);
                      setSysForm({ system_id: sys.id });
                      setSysFormError('');
                      setSysDialogOpen(true);
                    }}
                  >
                    Add
                  </Button>
                </Tooltip>
              </TableCell>
            </TableRow>
          ))}
          {environmentSystems.length === 0 && missingSystems.length === 0 && !loading && (
            <TableRow>
              <TableCell colSpan={2} align="center">
                <Typography color="text.secondary" py={3}>
                  No systems assigned to this environment yet.
                </Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </TableContainer>
  </Box>
)}
```

Also simplify `SysFormValues` to just `{ system_id: number | '' }` and update `emptySysForm` and the Add System dialog accordingly (no status select, no mock notes field).

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat: update EnvironmentDetail — remove system-level mock, add missing systems to Systems tab"
```

---

## Task 10: Components Tab

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Add the Components tab (tab === 2)**

Add imports at the top of the file:
```typescript
import { fetchEnvSubsystems, updateEnvSubsystem } from '../../store/environmentSlice';
import type { EnvironmentSubsystemResponse } from '../../types/environment';
```

Add selector for envSubsystems:
```typescript
const { envSubsystems } = useSelector((state: RootState) => state.environment);
```

Add the Components tab render after the Systems tab block:

```tsx
{tab === 2 && (
  <Box>
    <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
      <Button variant="contained" startIcon={<AddIcon />} onClick={openVersionDialog}>
        Record Version
      </Button>
    </Box>

    <TableContainer component={Paper}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>System / Subsystem</TableCell>
            <TableCell>Type</TableCell>
            <TableCell>Real / Mock</TableCell>
            <TableCell>Mock Notes</TableCell>
            <TableCell>Latest Version</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {envSubsystems.length === 0 && !loading && (
            <TableRow>
              <TableCell colSpan={5} align="center">
                <Typography color="text.secondary" py={3}>
                  No subsystems configured. Add systems with subsystems first.
                </Typography>
              </TableCell>
            </TableRow>
          )}
          {envSubsystems.map((sub) => (
            <TableRow
              key={sub.subsystem_id}
              hover
              sx={{ opacity: sub.is_mocked ? 0.6 : 1 }}
            >
              <TableCell>
                <Typography variant="caption" color="text.secondary">
                  {sub.system_name}
                </Typography>
                <Typography variant="body2" fontWeight="medium">
                  {sub.subsystem_name}
                </Typography>
              </TableCell>
              <TableCell>
                <Chip
                  label={sub.component_type.replace(/_/g, ' ')}
                  size="small"
                  variant="outlined"
                />
              </TableCell>
              <TableCell>
                <Chip
                  label={sub.is_mocked ? 'Mock' : 'Real'}
                  size="small"
                  color={sub.is_mocked ? 'warning' : 'success'}
                  onClick={() =>
                    dispatch(updateEnvSubsystem({
                      envId,
                      subsystemId: sub.subsystem_id,
                      data: { is_mocked: !sub.is_mocked },
                    }))
                  }
                  sx={{ cursor: 'pointer' }}
                />
              </TableCell>
              <TableCell>
                {sub.is_mocked ? (
                  <TextField
                    size="small"
                    placeholder="Mock notes (optional)"
                    value={sub.mock_notes ?? ''}
                    onChange={(e) =>
                      dispatch(updateEnvSubsystem({
                        envId,
                        subsystemId: sub.subsystem_id,
                        data: { mock_notes: e.target.value || null },
                      }))
                    }
                    sx={{ minWidth: 200 }}
                  />
                ) : (
                  <Typography variant="body2" color="text.secondary">—</Typography>
                )}
              </TableCell>
              <TableCell>
                {sub.is_mocked ? (
                  <Typography variant="body2" color="text.secondary">—</Typography>
                ) : sub.latest_version ? (
                  <Box>
                    <Typography variant="body2">{sub.latest_version.version_label}</Typography>
                    <Typography variant="caption" color="text.secondary">
                      {sub.latest_version.build_id} ·{' '}
                      {new Date(sub.latest_version.installed_at).toLocaleDateString()}
                    </Typography>
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">No version recorded</Typography>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  </Box>
)}
```

Update the Record Version dialog's subsystem dropdown to only show non-mocked subsystems:
```typescript
// In openVersionDialog, filter available subsystems
const allSubsystems = envSubsystems
  .filter((s) => !s.is_mocked)
  .map((s) => ({ ...s, id: s.subsystem_id, name: s.subsystem_name, systemName: s.system_name }));
setAvailableSubsystems(allSubsystems);
```

Adjust tab index for the old Versions tab content (versions tab moves from index 2 to not present anymore — the Versions content is replaced by Components). Remove the old versions tab render block (`{tab === 2 && ...versions...}`).

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat: add Components tab with per-subsystem real/mock toggle and latest version"
```

---

## Task 11: Extract Shared Topology Components

**Files:**
- Create: `frontend/src/components/topology/SystemGroupNode.tsx`
- Create: `frontend/src/components/topology/DependencyDetailPane.tsx`
- Modify: `frontend/src/pages/systems/SystemTopologyDiagram.tsx`

The goal is to extract `SystemGroupNode` and `DependencyDetailPane` from `SystemTopologyDiagram.tsx` so both the system and environment topology diagrams can reuse them.

- [ ] **Step 1: Create `frontend/src/components/topology/SystemGroupNode.tsx`**

```tsx
import { Box, Typography } from '@mui/material'

interface SystemGroupNodeProps {
  data: { label: string; isCurrent: boolean }
}

export default function SystemGroupNode({ data }: SystemGroupNodeProps) {
  const borderColor = data.isCurrent ? '#1976d2' : '#9e9e9e'
  const bgColor = data.isCurrent ? 'rgba(25,118,210,0.03)' : 'rgba(158,158,158,0.03)'
  const labelColor = data.isCurrent ? '#1976d2' : '#757575'

  return (
    <Box
      sx={{
        width: '100%',
        height: '100%',
        border: `2px dashed ${borderColor}`,
        borderRadius: 2,
        bgcolor: bgColor,
        position: 'relative',
        pointerEvents: 'none',
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: -11,
          left: 14,
          bgcolor: 'background.default',
          px: 0.75,
          lineHeight: 1,
        }}
      >
        <Typography
          variant="caption"
          sx={{
            fontWeight: 700,
            color: labelColor,
            fontSize: '0.7rem',
            letterSpacing: 0.4,
            textTransform: 'uppercase',
          }}
        >
          {data.label}
        </Typography>
      </Box>
    </Box>
  )
}
```

- [ ] **Step 2: Create `frontend/src/components/topology/DependencyDetailPane.tsx`**

Copy the `DependencyDetailPane` component from `SystemTopologyDiagram.tsx` verbatim into this new file. Add the necessary imports:

```tsx
import { Box, Chip, Divider, IconButton, Paper, Typography } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import type { ComponentDependencyResponse } from '../../types/dependency'

interface DependencyDetailPaneProps {
  dep: ComponentDependencyResponse
  onClose: () => void
}

export default function DependencyDetailPane({ dep, onClose }: DependencyDetailPaneProps) {
  // ... paste the existing component body here
}
```

- [ ] **Step 3: Update `SystemTopologyDiagram.tsx` to import from shared location**

Remove the `SystemGroupNode` and `DependencyDetailPane` function definitions from `SystemTopologyDiagram.tsx`. Replace with imports:

```typescript
import SystemGroupNode from '../../components/topology/SystemGroupNode'
import DependencyDetailPane from '../../components/topology/DependencyDetailPane'
```

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/topology/ frontend/src/pages/systems/SystemTopologyDiagram.tsx
git commit -m "refactor: extract SystemGroupNode and DependencyDetailPane to shared topology components"
```

---

## Task 12: Environment Topology Diagram

**Files:**
- Create: `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx`
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Create `frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx`**

Model this closely after `SystemTopologyDiagram.tsx`. Key differences:
- Data comes from `environmentService.getEnvironmentTopology(envId)` (local state, not Redux)
- Subsystem node data includes `is_mocked: boolean`
- Mocked nodes: dashed border + grey fill (override the component-type colour)
- Outside systems have `isCurrent: false` with label suffix `" — not in environment"`

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, Handle, Position,
  type Node, type Edge, MarkerType,
} from 'reactflow'
import 'reactflow/dist/style.css'
import dagre from '@dagrejs/dagre'
import { Box, Chip, Typography, CircularProgress, Alert } from '@mui/material'
import SystemGroupNode from '../../components/topology/SystemGroupNode'
import DependencyDetailPane from '../../components/topology/DependencyDetailPane'
import { environmentService } from '../../services/environmentService'
import type { EnvSubsystemNode } from '../../types/environment'
import type { ComponentDependencyResponse } from '../../types/dependency'

const COMPONENT_COLORS: Record<string, string> = {
  database: '#1976d2', cache: '#f57c00', message_queue: '#7b1fa2',
  web_service: '#388e3c', api_gateway: '#00796b', worker: '#e64a19',
  frontend: '#303f9f', other: '#616161',
}
const MOCK_COLOR = '#9e9e9e'

const NODE_WIDTH = 180
const NODE_HEIGHT = 70
const GROUP_PADDING = 40
const GROUP_LABEL_HEIGHT = 20
const GROUP_GAP = 80

function SubsystemNode({ data }: { data: { node: EnvSubsystemNode } }) {
  const s = data.node
  const isMocked = s.is_mocked
  const color = isMocked ? MOCK_COLOR : (COMPONENT_COLORS[s.component_type] ?? COMPONENT_COLORS.other)
  return (
    <Box
      sx={{
        width: NODE_WIDTH, height: NODE_HEIGHT,
        border: `2px ${isMocked ? 'dashed' : 'solid'} ${color}`,
        borderRadius: 1,
        bgcolor: isMocked ? 'rgba(158,158,158,0.06)' : 'background.paper',
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', px: 1, cursor: 'default',
        opacity: isMocked ? 0.75 : 1,
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {isMocked && (
        <Typography variant="caption" sx={{ color: MOCK_COLOR, fontSize: '0.6rem' }}>mocked</Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  )
}

const nodeTypes = { subsystemNode: SubsystemNode, systemGroupNode: SystemGroupNode }

function getLayoutedElements(
  subsystems: EnvSubsystemNode[],
  dependencies: ComponentDependencyResponse[],
  outsideSubsystems: EnvSubsystemNode[],
  outsideDependencies: ComponentDependencyResponse[],
  systemNames: Record<string, string>,
  envSystemIds: Set<number>,
  selectedDepId: number | null,
) {
  const allSubsystems = [...subsystems, ...outsideSubsystems]
  const allDependencies = [...dependencies, ...outsideDependencies]
  if (allSubsystems.length === 0) return { nodes: [], edges: [] }

  const groups = new Map<number, EnvSubsystemNode[]>()
  for (const s of allSubsystems) {
    if (!groups.has(s.system_id)) groups.set(s.system_id, [])
    groups.get(s.system_id)!.push(s)
  }

  interface GroupLayout {
    nodePositions: Map<number, { x: number; y: number }>
    contentWidth: number
    contentHeight: number
  }

  const groupLayouts = new Map<number, GroupLayout>()
  for (const [, subs] of groups) {
    const subIds = new Set(subs.map((s) => s.id))
    const g = new dagre.graphlib.Graph()
    g.setGraph({ rankdir: 'LR', ranksep: 80, nodesep: 40 })
    g.setDefaultEdgeLabel(() => ({}))
    subs.forEach((s) => g.setNode(String(s.id), { width: NODE_WIDTH, height: NODE_HEIGHT }))
    allDependencies.forEach((d) => {
      if (subIds.has(d.from_subsystem_id) && subIds.has(d.to_subsystem_id)) {
        g.setEdge(String(d.from_subsystem_id), String(d.to_subsystem_id))
      }
    })
    dagre.layout(g)

    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      minX = Math.min(minX, pos.x - NODE_WIDTH / 2); minY = Math.min(minY, pos.y - NODE_HEIGHT / 2)
      maxX = Math.max(maxX, pos.x + NODE_WIDTH / 2); maxY = Math.max(maxY, pos.y + NODE_HEIGHT / 2)
    })

    const positions = new Map<number, { x: number; y: number }>()
    subs.forEach((s) => {
      const pos = g.node(String(s.id))
      positions.set(s.id, { x: pos.x - minX, y: pos.y - minY })
    })
    groupLayouts.set(subs[0].system_id, {
      nodePositions: positions,
      contentWidth: maxX - minX,
      contentHeight: maxY - minY,
    })
  }

  // Sort: env systems first, outside systems after
  const allSysIds = [...groups.keys()]
  const sortedSysIds = allSysIds.sort((a, b) => {
    const aInEnv = envSystemIds.has(a) ? 0 : 1
    const bInEnv = envSystemIds.has(b) ? 0 : 1
    return aInEnv - bInEnv || a - b
  })

  const groupOrigins = new Map<number, { x: number; y: number }>()
  let cursorX = 0
  for (const sysId of sortedSysIds) {
    const layout = groupLayouts.get(sysId)!
    groupOrigins.set(sysId, { x: cursorX, y: 0 })
    cursorX += layout.contentWidth + GROUP_PADDING * 2 + GROUP_GAP
  }

  const groupNodes: Node[] = sortedSysIds.map((sysId) => {
    const layout = groupLayouts.get(sysId)!
    const origin = groupOrigins.get(sysId)!
    const inEnv = envSystemIds.has(sysId)
    const label = inEnv
      ? (systemNames[String(sysId)] ?? `System ${sysId}`)
      : `${systemNames[String(sysId)] ?? `System ${sysId}`} — not in environment`
    return {
      id: `group-${sysId}`,
      type: 'systemGroupNode',
      position: { x: origin.x, y: origin.y },
      data: { label, isCurrent: inEnv },
      style: {
        width: layout.contentWidth + GROUP_PADDING * 2,
        height: layout.contentHeight + GROUP_PADDING * 2 + GROUP_LABEL_HEIGHT,
      },
      selectable: false,
      draggable: false,
    }
  })

  const subsystemNodes: Node[] = allSubsystems.map((s) => {
    const layout = groupLayouts.get(s.system_id)!
    const nodeCenter = layout.nodePositions.get(s.id)!
    return {
      id: String(s.id),
      parentId: `group-${s.system_id}`,
      position: {
        x: nodeCenter.x - NODE_WIDTH / 2 + GROUP_PADDING,
        y: nodeCenter.y - NODE_HEIGHT / 2 + GROUP_PADDING + GROUP_LABEL_HEIGHT,
      },
      data: { node: s },
      type: 'subsystemNode',
    }
  })

  const edges: Edge[] = allDependencies.map((d) => ({
    id: String(d.id),
    source: String(d.from_subsystem_id),
    target: String(d.to_subsystem_id),
    label: d.label ?? d.dependency_type,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(d.direction === 'two_way' ? { markerStart: { type: MarkerType.ArrowClosed } } : {}),
    style: d.id === selectedDepId ? { stroke: '#1976d2', strokeWidth: 2.5 } : undefined,
  }))

  return { nodes: [...groupNodes, ...subsystemNodes], edges }
}

interface EnvironmentTopologyResponse {
  environment_id: number
  subsystems: EnvSubsystemNode[]
  dependencies: ComponentDependencyResponse[]
  system_names: Record<string, string>
  outside_subsystems: EnvSubsystemNode[]
  outside_dependencies: ComponentDependencyResponse[]
}

interface Props {
  envId: number
}

export default function EnvironmentTopologyDiagram({ envId }: Props) {
  const [data, setData] = useState<EnvironmentTopologyResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDepId, setSelectedDepId] = useState<number | null>(null)

  useEffect(() => {
    setLoading(true)
    environmentService.getEnvironmentTopology(envId)
      .then((d) => { setData(d as EnvironmentTopologyResponse); setLoading(false) })
      .catch((e) => { setError(e.message ?? 'Failed to load topology'); setLoading(false) })
  }, [envId])

  useEffect(() => { setSelectedDepId(null) }, [data])

  const envSystemIds = useMemo(() => {
    if (!data) return new Set<number>()
    return new Set(data.subsystems.map((s) => s.system_id))
  }, [data])

  const selectedDep = useMemo(() => {
    if (selectedDepId === null || !data) return null
    return [...data.dependencies, ...data.outside_dependencies]
      .find((d) => d.id === selectedDepId) ?? null
  }, [selectedDepId, data])

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [], edges: [] }
    return getLayoutedElements(
      data.subsystems,
      data.dependencies,
      data.outside_subsystems,
      data.outside_dependencies,
      data.system_names,
      envSystemIds,
      selectedDepId,
    )
  }, [data, envSystemIds, selectedDepId])

  const handleEdgeClick = useCallback((_event: React.MouseEvent, edge: Edge) => {
    const id = parseInt(edge.id, 10)
    setSelectedDepId((prev) => (prev === id ? null : id))
  }, [])

  if (loading) return <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
  if (error) return <Alert severity="error">{error}</Alert>
  if (!data || data.subsystems.length === 0) {
    return (
      <Box sx={{ textAlign: 'center', mt: 4, color: 'text.secondary' }}>
        <Typography>No subsystems configured. Add systems with subsystems to see the topology.</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', height: 500, border: 1, borderColor: 'divider', borderRadius: 1, overflow: 'hidden' }}>
      <Box sx={{ flex: 1, minWidth: '60%', position: 'relative' }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          onEdgeClick={handleEdgeClick}
        >
          <Background />
          <Controls />
          <MiniMap />
        </ReactFlow>
      </Box>
      {selectedDep && (
        <DependencyDetailPane dep={selectedDep} onClose={() => setSelectedDepId(null)} />
      )}
    </Box>
  )
}
```

- [ ] **Step 2: Add Topology tab to `EnvironmentDetail.tsx`**

Add the import:
```typescript
import EnvironmentTopologyDiagram from './EnvironmentTopologyDiagram'
```

Add the tab render after the Components tab:
```tsx
{tab === 3 && (
  <EnvironmentTopologyDiagram envId={envId} />
)}
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/environments/EnvironmentTopologyDiagram.tsx frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat: add environment topology diagram with mocked subsystem styling"
```

---

## Task 13: Verify Panel Extension

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Update the verify result computation in `EnvironmentDetail.tsx`**

The existing `allDepItems` and `nonSatisfiedItems` variables pull from `verifyResult.systems`. Keep those unchanged. Add new variables for the component-level section:

```typescript
const nonSatisfiedComponentItems = verifyResult?.component_dependencies?.filter(
  (d) => d.status !== 'satisfied'
) ?? []
```

- [ ] **Step 2: Add the Component Dependencies section to the verify panel**

Inside the verify result block, after the existing non-satisfied items table, add:

```tsx
{/* Component Dependencies section */}
{verifyResult && (verifyResult.component_total ?? 0) > 0 && (
  <Box sx={{ mt: 2 }}>
    <Typography variant="subtitle2" sx={{ mb: 1 }}>Component Dependencies</Typography>
    <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
      <Chip label={`${verifyResult.component_satisfied} satisfied`} color="success" size="small" />
      <Chip label={`${verifyResult.component_mocked} mocked`} color="warning" size="small" />
      <Chip label={`${verifyResult.component_missing} missing`} color="error" size="small" />
    </Box>
    {nonSatisfiedComponentItems.length > 0 && (
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>From Component</TableCell>
              <TableCell>Depends On</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {nonSatisfiedComponentItems.map((item) => (
              <TableRow key={`${item.from_subsystem_id}-${item.to_subsystem_id}`}>
                <TableCell>{item.from_subsystem_name}</TableCell>
                <TableCell>{item.to_subsystem_name}</TableCell>
                <TableCell>
                  <Chip label={item.dependency_type.replace(/_/g, ' ')} size="small" variant="outlined" />
                </TableCell>
                <TableCell>
                  <Chip
                    label={item.status}
                    size="small"
                    color={item.status === 'missing' ? 'error' : 'warning'}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    )}
  </Box>
)}
```

Also update the verify summary alert logic to incorporate component-level counts:
```tsx
} : verifyResult.missing_count === 0 && verifyResult.mocked_count === 0
    && (verifyResult.component_missing ?? 0) === 0 && (verifyResult.component_mocked ?? 0) === 0 ? (
  <Alert severity="success">All dependencies satisfied.</Alert>
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Fix any errors.

- [ ] **Step 3: Final integration smoke test**

Start both backend and frontend:
```bash
# Terminal 1
cd backend && uvicorn app.main:app --reload

# Terminal 2
cd frontend && npm run dev
```

Manual verification checklist:
- [ ] Navigate to an environment → Systems tab: assigned systems shown without status chip; missing systems appear greyed with Add button
- [ ] Add a system: Components tab shows its subsystems all as "Real"
- [ ] Toggle a subsystem to Mock: chip changes to warning colour; row dims; mock notes field appears
- [ ] Components tab: mocked subsystem shows "—" in Latest Version column
- [ ] Overview → Verify Environment: component dependencies section appears with correct satisfied/mocked/missing counts
- [ ] Topology tab: diagram renders with system group boxes; mocked subsystems have dashed grey borders; outside systems have "— not in environment" label
- [ ] Click an edge: side pane appears with dep details and endpoints
- [ ] Remove a system from environment: its subsystems disappear from Components tab

- [ ] **Step 4: Final commit**

```bash
git add frontend/src/pages/environments/EnvironmentDetail.tsx
git commit -m "feat: extend verify panel with component-level dependency results"
```
