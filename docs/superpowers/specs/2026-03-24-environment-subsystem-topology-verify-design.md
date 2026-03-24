# Design: Environment Subsystem Configuration, Topology & Verification

**Date:** 2026-03-24
**Status:** Approved

---

## Overview

Three related features that bring subsystem-level granularity to environments:

1. **Per-subsystem real/mocked configuration** — replace the coarse system-level mock status with individual subsystem toggles, stored in a new `environment_subsystem` table.
2. **Environment topology tab** — a ReactFlow diagram scoped to the environment showing all systems/subsystems and their component dependencies, with mocked subsystems visually distinct.
3. **Enhanced verification** — extend the existing dependency verify to also check component-level (subsystem) dependencies using the new per-subsystem mock status.

---

## 1. Data Model

### 1.1 New table: `environment_subsystem`

Stores per-subsystem real/mocked configuration for an environment.

| column | type | constraints |
|---|---|---|
| `id` | integer PK | auto |
| `environment_id` | integer FK → `environment.id` | not null, indexed |
| `subsystem_id` | integer FK → `subsystem.id` | not null, indexed |
| `tenant_id` | integer FK → `tenant.id` | not null, indexed |
| `is_mocked` | boolean | not null, default false |
| `mock_notes` | text | nullable |
| `created_at` | timestamptz | server default now() |
| `updated_at` | timestamptz | server default now() |

Unique constraint: `(environment_id, subsystem_id)`.

Note: this table is distinct from the existing `environment_subsystem_version` table (an append-only version log). These serve different purposes.

### 1.2 Removed from `environment_system`

`status` (VARCHAR) and `mock_notes` (TEXT) columns are dropped. The `EnvironmentSystem` row now only records the environment↔system relationship. The `EnvironmentSystemStatus` Python enum is deleted.

Orphaned rows: the `delete_environment` service function in `environment_service.py` must explicitly hard-delete all `environment_subsystem` rows for the environment before soft-deleting the environment (consistent with how `remove_system_from_environment` cleans up junction records).

### 1.3 Alembic migration

One revision with:
- `op.create_table("environment_subsystem", ...)` with indexes and unique constraint
- `op.drop_column("environment_system", "status")`
- `op.drop_column("environment_system", "mock_notes")`

---

## 2. Backend

### 2.1 Model changes (`app/db/models/environment.py`)

- Add `EnvironmentSubSystem` SQLAlchemy model
- Remove `status` and `mock_notes` mapped columns from `EnvironmentSystem`
- Delete `EnvironmentSystemStatus` enum (no longer needed)

### 2.2 Pydantic schema changes (`app/api/v1/schemas/environment.py`)

**Remove from existing schemas:**
- `EnvironmentSystemCreate`: remove `status` and `mock_notes` fields; remove `EnvironmentSystemStatus` import
- `EnvironmentSystemUpdate`: remove `status` and `mock_notes` fields
- `EnvironmentSystemResponse`: remove `status` and `mock_notes` fields

**Add new schemas:**
```
EnvironmentSubsystemResponse:
  subsystem_id, subsystem_name, component_type, technology,
  system_id, system_name, is_mocked, mock_notes,
  latest_version: VersionSummary | None

EnvironmentSubsystemUpdate:
  is_mocked: bool (optional)
  mock_notes: str | None (optional)

ComponentVerifyItem:
  from_subsystem_id, from_subsystem_name,
  to_subsystem_id, to_subsystem_name,
  dependency_type, status (satisfied|mocked|missing)

EnvironmentTopologyResponse:
  environment_id, subsystems: list[EnvSubsystemNode],
  dependencies: list[ComponentDependencyResponse],
  system_names: dict[int, str],
  outside_subsystems: list[SubsystemSummary],
  outside_dependencies: list[ComponentDependencyResponse]
```

**Update existing schema (in `app/api/v1/schemas/dependency.py`):**
- `VerifyResponse` gains: `component_dependencies: list[ComponentVerifyItem]`, `component_total: int`, `component_satisfied: int`, `component_mocked: int`, `component_missing: int`

### 2.3 Service changes

#### `app/services/environment_system_service.py`

This file is the primary home for system-in-environment operations and requires the most changes:

**`add_system_to_environment`**:
- Remove `status=data.status` and `mock_notes=data.mock_notes` from the `EnvironmentSystem(...)` constructor
- After `db.flush()`, fetch all non-deleted `SubSystem` rows for `data.system_id` and bulk-insert `EnvironmentSubSystem` rows with `is_mocked=False`. Use `INSERT ... ON CONFLICT (environment_id, subsystem_id) DO NOTHING` semantics to be idempotent.
- Import `EnvironmentSubSystem` model and `SubSystem` model

**`update_system_in_environment`**:
- Remove the `status` and `mock_notes` update logic entirely. This function may still exist for future fields, or can be removed if it has no remaining purpose.

**`remove_system_from_environment`**:
- Before deleting the `EnvironmentSystem` row, delete all `EnvironmentSubSystem` rows for subsystems belonging to this `system_id` in this `environment_id`.

**`list_systems_in_environment`**:
- Extend response to include a `missing_systems` list: systems that are targets of `SystemDependency` records (from any assigned system's `from_system_id`) but are not themselves in the environment. Computed in the same service call by loading `SystemDependency` records for all assigned systems and diffing against the assigned system ID set.

Remove `EnvironmentSystemStatus` import from this file.

**New functions in `environment_system_service.py`** (or a new `environment_subsystem_service.py`):

`get_environment_subsystems(db, env_id, tenant_id) -> list`:
- Load all `EnvironmentSubSystem` rows for the environment, joined with `SubSystem` + `System` (for names, component_type, technology).
- For each subsystem, fetch the latest `EnvironmentSubSystemVersion` record (the existing version table, ordered by `installed_at DESC`, limit 1) to populate `latest_version`.

`update_environment_subsystem(db, env_id, subsystem_id, data, tenant_id) -> EnvironmentSubSystem`:
- Load the row, apply `is_mocked` / `mock_notes` changes, flush, return.

#### `app/services/environment_service.py`

**`verify_environment`**:
- Remove the `EnvironmentSystemStatus.MOCK` check from the system-level pass. With `status` gone from `EnvironmentSystem`, system-level deps can only be `satisfied` (system is in env) or `missing` (system not in env). The `mocked_count` at the system level becomes 0; remove the mock branch.
- Add a component-level pass after the system-level pass:
  - Load all `ComponentDependency` records where `from_subsystem_id` belongs to any subsystem of an assigned system (join via `SubSystem.system_id IN system_ids`).
  - Load all `EnvironmentSubSystem` rows for `env_id` into a `{subsystem_id: is_mocked}` lookup.
  - For each component dep:
    - `satisfied` — `to_subsystem_id` in lookup and `is_mocked=False`
    - `mocked` — `to_subsystem_id` in lookup and `is_mocked=True`
    - `missing` — `to_subsystem_id` not in lookup
  - Accumulate into `component_total`, `component_satisfied`, `component_mocked`, `component_missing`, and a `component_dependencies` list of `ComponentVerifyItem` dicts.
- Return the extended dict with both system-level and component-level results.

Remove `EnvironmentSystemStatus` import from this file.

**`delete_environment`**:
- Before soft-deleting, hard-delete all `EnvironmentSubSystem` rows for `env_id` (consistent with how junction records are handled elsewhere).

**`get_environment_topology`** (new function):
- Load all `EnvironmentSubSystem` rows for `env_id` (with subsystem + system joins) to get the set of subsystems and their `is_mocked` flags.
- Load all `ComponentDependency` records where at least one endpoint (`from_subsystem_id` or `to_subsystem_id`) belongs to an env subsystem — same approach as `topology_service.get_system_topology`'s cross-system query. Include `selectinload(ComponentDependency.endpoints)`.
- For deps where the other endpoint is outside the env, collect those "outside" subsystems and their parent system names.
- Return an `EnvironmentTopologyResponse`-shaped dict.

### 2.4 API route changes (`app/api/v1/environments.py`)

New routes:
- `GET /environments/{env_id}/subsystems` → `list[EnvironmentSubsystemResponse]`
- `PATCH /environments/{env_id}/subsystems/{subsystem_id}` → `EnvironmentSubsystemResponse`
- `GET /environments/{env_id}/topology` → `EnvironmentTopologyResponse`

Updated routes:
- `GET /environments/{env_id}/systems` — response gains `missing_systems: list[SystemSummary]`
- `GET /environments/{env_id}/verify` — response now uses the extended `VerifyResponse` with component fields

---

## 3. Frontend

### 3.1 Type changes (`src/types/environment.ts`)

- Remove `EnvironmentSystemStatus` type
- Remove `status` and `mock_notes` from `EnvironmentSystemResponse`, `EnvironmentSystemCreate`, `EnvironmentSystemUpdate`
- Add `EnvironmentSubsystemResponse`, `EnvironmentSubsystemUpdate`
- Add `missing_systems: SystemSummary[]` to whatever type wraps the systems list response

### 3.2 Type changes (`src/types/dependency.ts`)

- Update `VerifyResponse` to add: `component_dependencies: ComponentVerifyItem[]`, `component_total: number`, `component_satisfied: number`, `component_mocked: number`, `component_missing: number`
- Add `ComponentVerifyItem` interface

### 3.3 Services

- `environmentService.ts`: add `listEnvironmentSubsystems`, `updateEnvironmentSubsystem`, `getEnvironmentTopology`

### 3.4 Redux (`src/store/environmentSlice.ts`)

- Remove `status`/`mock_notes` from environment system state and thunks
- Add `envSubsystems: EnvironmentSubsystemResponse[]` slice state
- Add `fetchEnvSubsystems`, `updateEnvSubsystem` async thunks

### 3.5 `EnvironmentDetail.tsx` cleanup

Remove all references to `EnvironmentSystemStatus`:
- Delete `ENV_SYS_STATUS_COLORS` constant
- Remove `status` from `SysFormValues` interface and `emptySysForm`
- Remove status Select and mock_notes TextField from the Add/Edit System dialog
- Remove status Chip column from the Systems table
- Remove `EnvironmentSystemStatus` import

### 3.6 Tab structure

Tabs: **Overview | Systems | Components | Topology**

(Versions tab renamed to Components; Topology tab added as new fourth tab.)

### 3.7 Systems tab

- Table columns: System name | Actions (edit/remove)
- Below assigned systems: a second section of greyed-out rows for `missing_systems` (systems that are declared dependencies but not in the env). Each missing row: system name, "Required by: X" caption, "Add" button (opens existing add-system dialog with system pre-selected).

### 3.8 Components tab (was Versions)

Unified subsystem view. Flat table with columns: System / Subsystem | Type | Real/Mock | Mock Notes | Latest Version | (record version button per row or global).

- **Real/Mock toggle**: clicking immediately fires `PATCH /environments/{env_id}/subsystems/{subsystem_id}` — no save button (optimistic toggle).
- **Mocked rows**: dimmed, inline mock_notes text field appears when mocked.
- **Latest version**: shown as `v2.1.0 (build-1234)` with relative date; "No version recorded" if absent; "—" if mocked.
- **Record Version button** (top right): subsystem dropdown shows only non-mocked subsystems.

### 3.9 Topology tab

New `EnvironmentTopologyDiagram` component (`src/pages/environments/EnvironmentTopologyDiagram.tsx`):
- Fetches from `GET /environments/{env_id}/topology` on mount.
- Same ReactFlow + dagre layout as `SystemTopologyDiagram` (reuse `SystemGroupNode`, `DependencyDetailPane` — extract to `src/components/topology/` shared location to avoid duplication).
- **Mocked subsystem nodes**: dashed border + muted grey fill (vs solid border + component-type colour for real).
- **Outside systems** (depended on but not in env): greyed-out `SystemGroupNode` box with label suffix "— not in environment".
- Edge click → `DependencyDetailPane` side pane.

### 3.10 Verify panel (Overview tab)

Gains a second section below the existing system-level table:

**Component Dependencies** section (hidden if `component_total === 0`):
- Counts row: `N satisfied | N mocked | N missing` chips.
- Table (non-satisfied rows only): From Component | Depends On | Type | Status.

---

## 4. Execution Order

1. Alembic migration (create `environment_subsystem`, drop columns from `environment_system`)
2. Backend model changes (`EnvironmentSubSystem` model, remove `status`/`mock_notes` from `EnvironmentSystem`, delete `EnvironmentSystemStatus` enum)
3. Pydantic schema changes (`schemas/environment.py` and `schemas/dependency.py`)
4. Service changes:
   - `environment_system_service.py`: remove status/mock, add subsystem auto-create/cleanup, add missing-systems logic
   - `environment_service.py`: fix verify (remove mock branch, add component pass), fix delete_environment, add get_environment_topology
5. API route changes (`environments.py`)
6. Frontend types (`environment.ts`, `dependency.ts`)
7. Frontend services + Redux slice
8. `EnvironmentDetail.tsx` cleanup (remove `EnvironmentSystemStatus` references)
9. Systems tab update (missing systems rows)
10. Components tab (replace Versions tab)
11. Topology tab (`EnvironmentTopologyDiagram`)
12. Verify panel extension

---

## 5. Verification

1. **Migration:** `alembic upgrade head` cleanly; `alembic downgrade -1` + `alembic upgrade head` round-trips.
2. **Add system to env:** `environment_subsystem` rows auto-created for each subsystem, all `is_mocked=false`.
3. **Remove system from env:** `environment_subsystem` rows cleaned up.
4. **Delete environment:** `environment_subsystem` rows are hard-deleted before soft-delete.
5. **Toggle mock:** `PATCH /environments/{id}/subsystems/{sub_id}` with `{"is_mocked": true}` → row updates; verify panel reflects mocked status.
6. **Verify endpoint — component deps:** a component dep where `to_subsystem` is mocked shows `mocked`; dep targeting a subsystem whose system isn't in env shows `missing`.
7. **Verify endpoint — system deps:** no more `mocked` status at system level; only `satisfied` or `missing`.
8. **Topology endpoint:** response includes all env subsystems + `is_mocked` per subsystem + outside deps.
9. **Frontend — Components tab:** mock toggle updates instantly; mocked rows dim; version column shows "—" for mocked subsystems.
10. **Frontend — Systems tab:** greyed-out missing systems appear with Add button.
11. **Frontend — Topology tab:** mocked nodes have dashed border; outside system boxes have "— not in environment" label.
