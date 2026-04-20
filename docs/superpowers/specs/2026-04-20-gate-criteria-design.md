# Gate Criteria + Release Overdue Tracking — Design

**Date:** 2026-04-20
**Status:** Approved by user — ready for implementation planning
**Related plan:** (to be created) `docs/superpowers/plans/2026-04-20-gate-criteria.md`

## Problem

`ReleaseGate` today is a single row with a free-text `acceptance_criteria` column and a binary pass/fail/override decision. It cannot express *individual* checklist items, who owns each one, when each is due, or whether any of them are late. There is also no "is this release on time?" signal anywhere in the product — only a `target_date` on `Release` with nothing aggregating against it.

We want:
1. Gates to be driven by discrete, individually-owned, individually-dated **criteria**.
2. A per-release **overdue** count derived from those criteria, so a late release is visible at a glance.
3. Gate auto-completion when all its criteria are resolved — reducing the number of manual pass/fail clicks.

## Scope

In scope:
- New `GateCriterion` table (1:N under `ReleaseGate`).
- CRUD + state transitions (`open` → `done`, reopen, soft-delete).
- Auto-pass of the parent `ReleaseGate` when its last `open` criterion flips to `done`.
- Computed overdue logic (no stored flag).
- Per-release overdue count exposed via the release list endpoint.
- `ReleaseGate.acceptance_criteria` text column removed (test-only data, no migration).
- Frontend: expandable gate rows with criterion list + overdue badge on release rows.

Explicitly out of scope (YAGNI):
- Gate-level due date (criteria cover it).
- Cross-release "my overdue activities" global view.
- Notifications / email / reminders (no notification infrastructure exists in the app).
- `in_progress`, `waived`, or any criterion state beyond `open`/`done`.
- Edits to `ReleaseEvent` (criteria are work items, not audit events — the event log stays as-is).
- Bulk criterion operations.

## Data model

### New table: `gate_criteria`

| Column | Type | Nullable | Notes |
|---|---|---|---|
| `id` | int PK | No | |
| `tenant_id` | int, FK `tenants.id` | No | Tenant scoping per project convention |
| `gate_id` | int, FK `release_gates.id` | No | `ON DELETE CASCADE` |
| `title` | String(250) | No | Short descriptor shown in row |
| `notes` | Text | Yes | Longer context |
| `due_date` | DateTime(timezone=True) | Yes | Drives overdue computation |
| `assigned_to_user_id` | int, FK `users.id` | Yes | Follows existing `<entity>_user_id` FK pattern |
| `status` | VARCHAR(20) | No | `native_enum=False`; values `open` / `done`; default `open` |
| `completed_at` | DateTime(timezone=True) | Yes | Set when `status` → `done` |
| `completed_by_user_id` | int, FK `users.id` | Yes | Set when `status` → `done` |
| `created_at` | DateTime(timezone=True) | No | `server_default=func.now()` |
| `updated_at` | DateTime(timezone=True) | No | `onupdate=func.now()` |
| `deleted_at` | DateTime(timezone=True) | Yes | Soft delete per project convention |

**Indexes:**
- `(tenant_id, gate_id)` — list criteria for a gate, tenant-scoped
- `(tenant_id, assigned_to_user_id, status)` — future "my open items" view (low-cost to add now)

**Conventions (per `CLAUDE.md`):**
- `native_enum=False` on the `status` column.
- Soft delete via `deleted_at`; hard delete only for dependency/junction records.
- `tenant_id` filter on every query.

### Modified table: `release_gates`

- **Drop** column `acceptance_criteria`. Test data only, no migration body needed — the Alembic migration just issues `op.drop_column`.
- No other changes to `ReleaseGate`. Existing `status`, `decided_by`, `decided_at`, `decision_notes` remain as-is and keep their current semantics. Auto-pass writes these fields like a manual pass would.

## Behaviour

### Criterion lifecycle

```
  [create]        [complete]        [reopen]
     │                │                │
     ▼                ▼                ▼
   open  ──────────► done  ──────────► open
```

- **Create**: `status='open'`, `completed_at=null`, `completed_by_user_id=null`.
- **Complete** (`POST /gate-criteria/{id}/complete`): sets `status='done'`, `completed_at=now()`, `completed_by_user_id=current_user.id`. May trigger gate auto-pass (see below).
- **Reopen** (`POST /gate-criteria/{id}/reopen`): sets `status='open'`, clears `completed_at` and `completed_by_user_id`. Does NOT un-pass the parent gate.
- **Edit** (`PUT /gate-criteria/{id}`): title, notes, due_date, assigned_to_user_id. Does not change status.
- **Delete** (`DELETE /gate-criteria/{id}`): sets `deleted_at=now()`. Deleted criteria do not participate in auto-pass logic or overdue counts.

### Gate auto-pass rule

When a criterion transitions to `done`, check the parent gate:

> If the gate's status is `pending` AND every non-deleted criterion under the gate has `status='done'`, transition the gate to `passed`:
> - `status='passed'`
> - `decided_at=now()`
> - `decided_by=current_user.id`
> - `decision_notes='auto: all criteria met'`

One-way: reopening a criterion after auto-pass does NOT flip the gate back to `pending`. Rationale: avoids whiplash UI state and lets the gate decision be a permanent record. If a pass was wrong, a human uses the existing override flow.

A gate with **zero** criteria does NOT auto-pass. Empty criteria list is treated as "no checklist defined yet" and the gate remains `pending` until criteria are added and completed, or a human uses the existing pass/fail/override endpoints.

### Overdue semantics

Pure computation — no denormalised column.

- **Criterion overdue** ⇔ `deleted_at IS NULL AND status='open' AND due_date IS NOT NULL AND due_date < now()`.
- **Gate has overdue** = any of its non-deleted criteria are overdue (derived; not stored).
- **Release overdue count** = total overdue criteria across all gates for a release.

Evaluated at query time in the service layer. `now()` is UTC `datetime.now(timezone.utc)`.

## API

All under `/api/v1`. Tenant-scoped via `current_user.active_tenant_id` (not `.tenant_id` — handles impersonation).

### New endpoints

| Method | Path | Purpose | Response |
|---|---|---|---|
| `POST` | `/releases/{release_id}/gates/{gate_id}/criteria` | Create criterion under gate | 201 `GateCriterionRead` |
| `GET` | `/releases/{release_id}/gates/{gate_id}/criteria` | List criteria for gate | 200 `list[GateCriterionRead]` |
| `PUT` | `/gate-criteria/{criterion_id}` | Edit title/notes/due_date/assignee | 200 `GateCriterionRead` |
| `POST` | `/gate-criteria/{criterion_id}/complete` | Mark done; may auto-pass gate | 200 `GateCriterionRead` |
| `POST` | `/gate-criteria/{criterion_id}/reopen` | Reopen | 200 `GateCriterionRead` |
| `DELETE` | `/gate-criteria/{criterion_id}` | Soft delete | 204 |
| `GET` | `/releases/{release_id}/overdue-criteria` | Flat list of overdue criteria for the release | 200 `list[GateCriterionWithGate]` |

`GateCriterionWithGate` = `GateCriterionRead` plus `gate_id`, `gate_name`, for display without a second round-trip.

### Modified endpoints

- `GET /releases/{release_id}/gates` — response enriched so each gate includes `criteria: list[GateCriterionRead]` and `overdue_criterion_count: int` for frontend rendering without N+1.
- `GET /releases` (list) — each item's `ReleaseListItemRead` gains `overdue_criterion_count: int`, computed by a grouped query (same shape as existing `blocker_count`, `phase_count`, `scope_count`).

### Response shape

```python
class GateCriterionRead(BaseModel):
    id: int
    gate_id: int
    title: str
    notes: Optional[str]
    due_date: Optional[datetime]
    assigned_to_user_id: Optional[int]
    assigned_to_username: Optional[str]  # populated by service for convenience
    status: str  # "open" | "done"
    completed_at: Optional[datetime]
    completed_by_user_id: Optional[int]
    is_overdue: bool  # computed at serialize time
    created_at: datetime
    updated_at: datetime
```

`is_overdue` is a serializer-side computation so clients never have to reimplement the rule.

### Auth

- All endpoints require `get_current_user` (authenticated).
- No role-gating beyond that for v1 — any tenant member can create/complete criteria. Role-based restriction (e.g. only assignee can complete) is deferred. This matches the current gate decision endpoints' openness.

### Events (outbox pattern per project convention)

- `GateCriterionCreated` — emitted on create
- `GateCriterionCompleted` — emitted on complete
- `GateCriterionReopened` — emitted on reopen
- `GateAutoPassed` — emitted when auto-pass fires (distinct from existing `GatePassed` so consumers can tell the two apart)

Use `publish_event()` in the same transaction as the business write — never `db.commit()` in services.

## Frontend

### Components touched

| File | Change |
|---|---|
| `frontend/src/components/releases/GatesTable.tsx` | Expandable rows; each row shows progress ("3 / 5 done") and a red overdue badge when applicable. |
| `frontend/src/components/releases/GatesTable.tsx` (or new sibling) | Inline criteria list under expanded row; inline "Add criterion" affordance. |
| NEW: `frontend/src/components/releases/CriterionDialog.tsx` | Form for create/edit — title, notes, due_date (date-time picker), assignee picker. |
| NEW: `frontend/src/components/releases/CriterionRow.tsx` | Single criterion row: checkbox (complete/reopen), title, due-date chip (red when overdue), assignee chip, overflow menu (edit/delete). |
| `frontend/src/components/releases/GateDecisionDialog.tsx` | **Unchanged.** Manual decision flow untouched. |
| `frontend/src/services/releaseService.ts` | Add criterion CRUD + complete/reopen methods. |
| `frontend/src/store/releaseSlice.ts` | Thunks + slice state for criteria list on the currently-viewed release; optimistic update on `complete`. |
| `frontend/src/pages/releases/ReleaseList.tsx` (or the component rendering the list) | Overdue badge on release rows with `overdue_criterion_count > 0`. |

### Overdue visual treatment

- Chip red variant. Label format: `"overdue: <N>"` or `"overdue"` when N=1.
- No icon-only; text labels are required for accessibility.
- Column order and existing columns preserved.

### Empty states

- Gate with zero criteria: show a muted "No criteria yet. [Add criterion]" row under the expanded gate.
- Release with no gates: unchanged from today.

## Testing

### Backend

- Model tests: `gate_criteria` insert/soft-delete/timestamp behaviour; FK cascade on gate delete.
- Service tests: create, edit, complete (including auto-pass edge cases below), reopen, delete. Overdue computation.
- **Auto-pass edge cases** — explicit tests for:
  - Single-criterion gate: completing the one criterion auto-passes.
  - Multi-criterion gate: only the last `done` triggers auto-pass.
  - Gate with zero criteria: NEVER auto-passes.
  - Deleted criterion: not counted; completing all non-deleted still auto-passes.
  - Gate already in `passed`/`failed`/`overridden`: no double-transition, no second event.
  - Reopening a criterion after auto-pass: gate stays `passed`, no event fired.
- API integration tests: happy path for each endpoint + tenant isolation (criterion from another tenant returns 404).
- Overdue query tests: `now()` boundary, timezone-aware, null due_date is never overdue.
- Release list test: `overdue_criterion_count` aggregation matches a hand-counted expectation.

### Frontend

- Component tests for `CriterionRow` (overdue chip shows; completing calls the thunk).
- Component tests for `CriterionDialog` form validation.
- Snapshot/integration for `GatesTable` expansion.

## Migrations

Alembic revision: one migration that:
1. `op.create_table("gate_criteria", ...)` with all columns + indexes defined above.
2. `op.drop_column("release_gates", "acceptance_criteria")`.

No data migration (test data only). Written manually — not `--autogenerate` (see `CLAUDE.md` pitfall note).

## Rollout

- Behind no feature flag. Branch merges into `main` through the normal GitLab MR flow.
- Backend + frontend ship together in one branch; no backward-compat shims needed (test data only).
- Seed data (if any release-gate seed exists) is updated to match the new model.

## Risks and open questions

- **Auto-pass as irreversible**: discussed and accepted. Override flow covers the escape hatch.
- **Role-based restrictions on criterion completion**: deferred; easy to add later by hooking into the existing `require_role` decorator.
- **Assignee notification**: no infrastructure exists. Not in scope.
- **Gate-level due date**: not added — adding later is cheap if needed.
