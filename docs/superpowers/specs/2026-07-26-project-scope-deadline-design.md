# Project-release scope deadline + scope-signoff gate

**Date:** 2026-07-26
**Status:** Approved (design) — pending implementation plan
**Scope:** Non-enterprise (project) releases only

## Problem

Project (non-enterprise) releases have no way to document a scope baseline. There is
no field marking the point after which added stories/issues represent scope creep on
the original agreed scope. Teams want to (a) record a **scope deadline** per project
release and (b) get a **scope sign-off gate** created automatically so a Release Manager
formally signs the scope off.

This is distinct from and additive to the existing post-approval `'Scope Change'` event
mechanism (`release_scope_service.py` + `ScopeChangeKindRule`), which is unchanged. The
scope deadline is the "original scope" baseline; approval-based scope-change events keep
working as they do today.

## Decisions (locked)

1. **Role-based assignment** — the scope-signoff criterion is assigned to the
   `Release Manager` **role**, not a single user. Requires a new `assigned_role` column
   on `GateCriterion`.
2. **Creep baseline = scope deadline** — an item is scope creep if the time it entered
   the release is after `scope_deadline`. Surfaced as a computed count + per-item flag.
3. **Gate auto-created on set, idempotent, kept if the date is later cleared.**
4. **Enterprise = hard reject** — setting `scope_deadline` on an enterprise release
   returns 422.
5. **Due-date sync** — if `scope_deadline` changes while the gate is still `pending`,
   the gate's `due_date` is re-synced to the new value; a decided gate is never touched.

## Data model

### `release.scope_deadline`
- New column on `Release`: `scope_deadline = Column(DateTime(timezone=True), nullable=True)`.
- Meaningful only when `release_kind == "project"`.
- Alembic migration: manual `op.add_column("release", ...)`. No backfill.

### `gate_criterion.assigned_role`
- New column on `GateCriterion`: `assigned_role = Column(String(50), nullable=True)`.
  Enum stored as VARCHAR (`native_enum=False` convention — plain String here).
- A criterion is assigned to **either** a user (`assigned_to_user_id`) **or** a role
  (`assigned_role`), never both. This is a soft invariant enforced in the service /
  schema, not a DB constraint.
- Valid values are the `Role` string constants in `app/core/security.py`
  (`"Release Manager"`, etc.).
- Alembic migration: manual `op.add_column("gate_criterion", ...)`. Existing rows get
  `NULL` and are unaffected.

## Behaviour

### Setting the scope deadline
- `ReleaseCreate` and `ReleaseUpdate` gain an optional `scope_deadline` field.
- On create/update, if `scope_deadline` is provided and `release_kind == "enterprise"`,
  raise 422 (`scope_deadline is only valid on project releases`).
- Transition **unset → set** (on create or update) triggers gate auto-creation (below).

### Auto-created scope-signoff gate
When `scope_deadline` goes from unset to set, `release_service` creates — idempotently —
one gate on the release:
- Gate: `name = "Scope Sign-off"`, `due_date = scope_deadline`, `status = "pending"`.
- One criterion: `title = "Scope signed off"`, `assigned_role = "Release Manager"`,
  `status = "open"`.
- **Idempotency:** if a (non-deleted) gate named `"Scope Sign-off"` already exists on the
  release, skip creation entirely.
- Publishes the existing `ReleaseGateCreated` event (reuse `create_gate` path so events
  and outbox behaviour are consistent).

Lifecycle edge cases:
- Deadline later **cleared** (set → null): gate is **kept** as-is.
- Deadline **changed** (set → different value): if the "Scope Sign-off" gate is still
  `pending`, re-sync its `due_date` to the new deadline. If the gate is
  passed/failed/overridden, leave it untouched.

### Scope-creep computation
Define **entered-release time** for a `ReleaseChange` as:
> earliest `ReleaseChangeReleaseHistory.moved_at` where `to_release_id == release.id`,
> falling back to `ReleaseChange.created_at` when no such history row exists
> (item created directly in the release).

An item is **scope creep** iff `scope_deadline` is set and entered-release time
`> scope_deadline`. Deleted items (`deleted_at` set) are excluded.

Surfaced as:
- `scope_creep_count: int` on `ReleaseListItemRead` and `ReleaseRead` (0 when no deadline
  is set). Computed alongside the existing scope KPIs.
- A per-item boolean (e.g. `is_scope_creep`) in the Scope tab item payload so creep items
  can be visibly tagged.

### Completion authorisation for role-assigned criteria
- A criterion assigned via `assigned_role` may be marked complete by any user whose role
  equals `assigned_role`, or by an Admin.
- Enforced in the criterion-complete service path (403 otherwise).
- User-assigned criteria (`assigned_to_user_id`) keep their existing completion rules.

## Schemas (Pydantic)

- `ReleaseCreate` / `ReleaseUpdate`: add optional `scope_deadline: datetime | None`.
- `ReleaseRead` / `ReleaseListItemRead`: add `scope_deadline` and `scope_creep_count`.
- `GateCriterionCreate` / `GateCriterionUpdate`: add optional `assigned_role: str | None`
  (validate it's a known `Role` value and mutually exclusive with `assigned_to_user_id`).
- `GateCriterionRead`: add `assigned_role`. Keep `assigned_to_username` hydration for the
  user-assignment case.
- Scope tab item read schema: add `is_scope_creep: bool`.

## Frontend

- **ReleaseForm** (`pages/releases/ReleaseForm.tsx`): a `scope_deadline` date/datetime
  field, rendered only when `release_kind == "project"`. Hidden (and not sent) for
  enterprise.
- **Criterion rendering** (`components/releases/GatesTable.tsx`): when a criterion has
  `assigned_role`, render it as the role (e.g. "Release Manager (role)") instead of a
  username. The complete control is enabled only for eligible users (role match or Admin);
  disabled otherwise.
- **Scope tab**: tag creep items with a chip/icon driven by `is_scope_creep`; optional
  header count sourced from `scope_creep_count` (e.g. "N added after scope deadline").
- **Redux/types**: extend release + criterion + scope-item TypeScript types with the new
  fields. Follow existing slice/service patterns.

## Testing

**Backend**
- Setting `scope_deadline` on a project release creates the gate + criterion with the
  right name/role/due_date.
- Re-setting / setting again is idempotent (no duplicate gate).
- Setting `scope_deadline` on an enterprise release → 422.
- Clearing the deadline leaves the gate in place.
- Changing the deadline re-syncs `due_date` while pending; does **not** touch a decided gate.
- `scope_creep_count` correct across (a) items created directly in the release and
  (b) items moved in via history — before vs after the deadline; deleted items excluded.
- Role-based completion authz: allowed for a Release Manager and for Admin; denied (403)
  for other roles.
- Mutual-exclusion validation: criterion cannot set both `assigned_role` and
  `assigned_to_user_id`.

**Frontend**
- `scope_deadline` field visible only for `release_kind == "project"`.
- Role-assigned criterion renders the role, not a username; complete control gated by
  eligibility.
- Creep items tagged in the Scope tab.

## Out of scope (YAGNI)
- Backfilling scope-signoff gates for existing project releases.
- Notifications / reminders on the gate.
- Multiple assignees (mixed user+role) on a single criterion.
- Any change to enterprise `late_scope` logic or the existing post-approval
  `'Scope Change'` event mechanism.

## Affected files (indicative)
- `backend/app/db/models/release.py` — add `scope_deadline`.
- `backend/app/db/models/gate_criterion.py` — add `assigned_role`.
- `backend/alembic/versions/*` — one migration adding both columns.
- `backend/app/services/release_service.py` — set/clear/change deadline + gate orchestration.
- `backend/app/services/release_gate_service.py` — reuse `create_gate`; role-assignee support.
- `backend/app/services/gate_criterion_service.py` (or equivalent) — role completion authz,
  mutual-exclusion validation.
- `backend/app/services/release_scope_service.py` or a KPI helper — `scope_creep_count`,
  `is_scope_creep`.
- `backend/app/api/v1/schemas/release.py`, `.../release_gate.py`, `.../gate_criterion.py`
  and the scope-item schema.
- `frontend/src/pages/releases/ReleaseForm.tsx`,
  `frontend/src/components/releases/GatesTable.tsx`, the Scope tab component,
  `frontend/src/types/release.ts`, relevant slice/service files.
