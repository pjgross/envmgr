# Post-Implementation Reviews (Phase 5, Sub-Project 4)

**Date:** 2026-07-29
**Status:** Design approved, ready for implementation plan
**Programme:** Phase 5 — DORA Metrics, Health Dashboard & PIR
**Base branch:** `main` (SP1 + SP2 + SP3 merged)

## Context

Sub-project 4 of Phase 5. Adds **Post-Implementation Reviews (PIR)** — a structured
retrospective attached to a release, optionally linked to a triggering incident. PIR is
greenfield (the phase-5 doc claims it was "defined in Phase 3"; it was not — no PIR code
exists). This sub-project also finishes the **PIR panel on the incident detail page**, which
SP1 (Incident Tracking) deliberately deferred to here.

Decisions locked during brainstorming:
- **A PIR is release-scoped and optional**: at most **one PIR per release** (`release_id`
  unique), created **on demand** — most small/low-risk releases won't have one; a PIR is
  created when a release warrants a review (e.g. something went wrong, or lessons to record).
- **The incident link is optional**: `incident_id` is nullable. A PIR often documents a
  release's outcome or development-process improvements with **no** incident involved.
- **The release-closure gate is deferred** — SP4 builds the PIR record + API + panels;
  wiring "PIR-complete blocks release closure" into the release lifecycle is a later
  follow-on. (The release detail still *shows* whether a PIR exists and is complete.)
- Simple `draft`/`complete` status (no lifecycle state machine); single `action_plan` text
  field (no action-item sub-records); no PIR custom fields (all deferrable).

### Existing pieces (verified)

- `Release` (`release`): the PIR's owner (`release_id`). Release detail is a tabbed page.
- `Incident` (`incident`, SP1): optional link target. `incident_service.get_incident_detail`
  already returns a rich detail dict and was built with a **PIR placeholder in mind**
  (the SP1 IncidentDetail has no PIR panel yet); the incident list row builder is where a
  `pir_status` column is added.
- No PIR model, API, or UI exists. `ReleaseGate` exists but is **not** used here (gate
  deferred).

## Goal

An optional, release-scoped PIR record (optionally incident-linked) with CRUD via the
release, surfaced on the release detail page, the incident detail page (the SP1-deferred
panel), and a PIR-status column on the incident list.

## Non-Goals

- **Release-closure gate** (PIR-complete blocking closure) — deferred.
- **PIR custom fields**, **action-item sub-records**, **PIR lifecycle state machine** — deferred.
- Any change to the release lifecycle.

## Design

### 1. Data model — `PIR` (`backend/app/db/models/pir.py`)

| Column | Type | Notes |
|---|---|---|
| `tenant_id` | FK tenant, indexed | tenant scoping |
| `release_id` | FK `release`, **unique** | one PIR per release; the owner |
| `incident_id` | FK `incident`, nullable | optional triggering/related incident |
| `summary` | Text, nullable | short overview |
| `root_cause` | Text, nullable | |
| `what_went_well` | Text, nullable | |
| `what_went_wrong` | Text, nullable | |
| `action_plan` | Text, nullable | follow-up actions / improvements |
| `status` | String(10) | `draft` (default) \| `complete` |
| `completed_at` | DateTime(tz), nullable | set when status → `complete`, cleared if it leaves |
| `created_by` | FK user, nullable | |
| `deleted_at` | DateTime(tz), nullable | soft delete |

Unique constraint on `(release_id)` where not soft-deleted — enforce "one PIR per release"
in the service (create returns 409 if a non-deleted PIR already exists for the release; a
plain unique index on `release_id` is added too, with the service handling the soft-deleted
edge). Manual Alembic migration (`op.create_table`).

### 2. Service — `backend/app/services/pir_service.py`

- `get_for_release(db, tenant_id, release_id) -> PIR | None` — the release's non-deleted PIR.
- `create_for_release(db, tenant_id, release_id, data, user_id) -> PIR` — validates the
  release belongs to the tenant (404), rejects a duplicate (409 if a PIR already exists),
  validates `incident_id` (if given) belongs to the tenant (422 otherwise); status defaults
  `draft`.
- `update(db, tenant_id, release_id, data) -> PIR` — patch fields incl. `status` and
  `incident_id` (re-validate tenant); entering `complete` sets `completed_at`, leaving it
  clears `completed_at`.
- `delete(db, tenant_id, release_id)` — soft delete.
- `pir_status_for_incidents(db, tenant_id, incident_ids) -> dict[int, str]` — bulk map
  incident_id → `complete`/`draft`/`none` (a single query over PIRs whose `incident_id` is
  in the set), used by the incident list to avoid N+1.
- `get_for_incident(db, tenant_id, incident_id) -> PIR | None` — the PIR referencing this
  incident (for the incident detail panel).
- All queries tenant-scoped + `deleted_at IS NULL`.

### 3. API — `backend/app/api/v1/pir.py` (mounted at `/api/v1`)

- `GET /api/v1/releases/{release_id}/pir` → the PIR or `204`/`null` when none.
- `POST /api/v1/releases/{release_id}/pir` → create (201), `409` if one exists.
- `PATCH /api/v1/releases/{release_id}/pir` → update.
- `DELETE /api/v1/releases/{release_id}/pir` → `204` soft delete.
- JWT auth; any authenticated tenant user (consistent with incidents). Tenant from
  `current_user.active_tenant_id`.

**Incident integration (finishes SP1's deferred panel):**
- `incident_service.get_incident_detail` gains a `pir` field = `pir_service.get_for_incident`
  result serialized (`release_id`, `status`, `root_cause`, `action_plan`, `summary`) or null.
- The incident **list** row builder adds `pir_status` via
  `pir_service.pir_status_for_incidents` (bulk). Add `pir_status` to the incident list-row
  schema + TS type.

### 4. Frontend

- `frontend/src/types/pir.ts`, `frontend/src/services/pirService.ts`
  (`getForRelease(releaseId)`, `create/update/remove`).
- **Release detail — PIR tab** (`components/releases/ReleasePirTab.tsx`): if no PIR, an
  empty state + **"Create PIR"** button; once created, an editable form (summary, root cause,
  what went well / wrong, action plan) + a **status toggle** (Draft ⇄ Complete) with a
  completion chip/date. Add the tab to `ReleaseDetail.tsx` following the existing tab pattern.
- **Incident detail — PIR panel** (`IncidentDetail.tsx`, the SP1 placeholder → real): shows
  the linked PIR (root cause / action plan / status) when `detail.pir` is present; otherwise
  a **"Create PIR"** button that creates a PIR on the incident's **`fix_release`** with
  `incident_id` set — **disabled with a hint** ("Link a fix release first") when the incident
  has no `fix_release_id` (PIR is release-scoped).
- **Incident list — "PIR Status" column** (`IncidentList.tsx`): renders `pir_status`
  (Complete / Draft / — for none) as a chip.

### 5. Migration + wiring

Manual Alembic migration for `pir`; register the model in `app/db/models/__init__.py`;
mount the router in `app/main.py`. No tenant-seed changes.

## Files

**Backend — create:** `app/db/models/pir.py`, `app/api/v1/schemas/pir.py`,
`app/services/pir_service.py`, `app/api/v1/pir.py`, `alembic/versions/<rev>_pir.py`, tests
`tests/services/test_pir_service.py`, `tests/integration/test_pir_api.py`.
**Backend — modify:** `app/db/models/__init__.py`, `app/main.py`,
`app/services/incident_service.py` (add `pir` to detail + `pir_status` to list rows),
`app/api/v1/schemas/incident.py` (add `pir` to detail schema, `pir_status` to list-row schema).

**Frontend — create:** `src/types/pir.ts`, `src/services/pirService.ts`,
`src/components/releases/ReleasePirTab.tsx`.
**Frontend — modify:** `src/pages/releases/ReleaseDetail.tsx` (PIR tab),
`src/pages/incidents/IncidentDetail.tsx` (PIR panel),
`src/pages/incidents/IncidentList.tsx` (PIR Status column), `src/types/incident.ts`
(add `pir` to detail, `pir_status` to list row).

## Testing

**Backend (`pir_service`):**
- create for a release (draft default); duplicate create → 409; release from another tenant
  → 404; `incident_id` from another tenant → 422.
- update → `complete` sets `completed_at`; back to `draft` clears it.
- `get_for_release` / `get_for_incident` return the right PIR; soft delete hides it (and a
  new PIR can then be created for the release).
- `pir_status_for_incidents` maps complete/draft/none correctly in one query.
- Tenant isolation on all reads.

**Backend (API + incident integration):**
- release PIR CRUD via the endpoints; 409 on duplicate.
- `GET /incidents/{id}` includes `pir` when a PIR references it; incident list rows include
  `pir_status`.

**Frontend:** `pirService` calls; a light `ReleasePirTab` render test (empty-state → create →
edit → complete toggle) and the incident PIR-panel "disabled when no fix release" case.

`tsc --noEmit` clean; full backend suite green; `vitest run` green.

## Risks

- **One-PIR-per-release enforcement across soft-deletes:** a plain DB unique index on
  `release_id` would block creating a new PIR after the old one is soft-deleted. Enforce
  uniqueness in the service (check for a non-deleted PIR) and use a partial/plain index as a
  backstop; the create test covers the soft-delete-then-recreate path.
- **Incident "Create PIR" needs a release:** because PIR is release-scoped, the incident
  panel can only create a PIR when the incident has a `fix_release_id`. This is handled by
  disabling the button with a hint; the incident-detail panel is otherwise read-only for PIR
  content (editing happens on the release PIR tab). Documented so it isn't read as a bug.
