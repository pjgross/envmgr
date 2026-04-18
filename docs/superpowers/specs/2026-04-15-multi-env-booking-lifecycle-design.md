# Multi-Environment Booking Requests with Inline Lifecycle Actions

**Date:** 2026-04-15
**Status:** Design — awaiting implementation plan

## Context

Two gaps in the current booking feature need fixing together because they share the same UI surface:

1. **Stale approve/reject UI.** `BookingCalendar` and `BookingList` still use hardcoded `Approve` / `Reject` / `Cancel` buttons calling legacy `/approve`, `/reject`, `/cancel` endpoints. These don't work with the new lifecycle templates where transitions are defined per booking type. `BookingDetail` already renders dynamic transitions from `getAllowedTransitions` — the list and calendar need the same treatment.
2. **Multi-environment requests.** A team needs to book several environments as one coordinated request (shared project, dates, booking type, custom fields), but each environment must be approvable / rejectable / transitioned independently. Conflicts are informational, not hard blocks — owners coordinate via "willing to share" acknowledgements with notes.

Folding these together avoids rewriting the list/calendar UI twice. The inline per-row transition menu introduced for (1) becomes the per-environment approval UI once (2) exists — same component, cleaner semantics.

## Goals

- One booking request can cover N environments; each env is transitioned independently through the request's lifecycle.
- Replace hardcoded approve/reject/cancel everywhere with dynamic lifecycle-driven transitions.
- Soft conflict detection with a per-pair acknowledgement model — owner (or delegate) records "willing to share" + notes.
- List makes unacknowledged conflicts visible at a glance.
- `/transition` is the single canonical state-change endpoint.

## Non-goals

- No hard enforcement of `exclusive_use` — it stays informational. "People may request sole access but can't always be accommodated."
- No per-env lifecycle templates — the request defines one lifecycle applied independently to each env.
- No request-level transitions — transitions are always per env. Request status is derived (rollup), not stored.
- No automatic ack timeout / auto-resolution — stale acks stay surfaced via the indicator.
- No bulk actions across multiple env bookings in the list — per-row only.

## Data model

### New: `booking_request` (parent)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | Tenant-scoped. |
| `project_name` | str | |
| `booking_type_id` | int FK | Determines lifecycle template. |
| `start_date` | datetime | Request default window. |
| `end_date` | datetime | |
| `notes` | text, nullable | |
| `context_tag` | str | `'none'` / `'deployment'` / `'regression'`. Matches existing booking enum (native_enum=False). |
| `exclusive_use_requested` | bool | Informational flag — preference, not enforcement. |
| `custom_fields` | JSONB | Request-level — shared across children. |
| `booked_by` | int FK user | Request owner. |
| `delegate_user_ids` | int[] | Users who may acknowledge conflicts on owner's behalf. |
| `created_at` / `updated_at` / `deleted_at` | datetime | Soft-delete pattern. |

### Refactored: `booking` (now per-environment child)

| Column | Change |
|---|---|
| `id`, `tenant_id`, `environment_id`, `status`, `created_at`, `updated_at`, `deleted_at` | Unchanged. |
| `booking_request_id` | **New** — FK → `booking_request.id`, NOT NULL after migration Step 2. |
| `start_date`, `end_date` | **Kept** — default to parent window on creation; may be overridden per env (D3). |
| `project_name`, `booking_type_id`, `notes`, `exclusive_use`, `context_tag`, `custom_fields`, `booked_by` | **Dropped** in migration Step 2 — moved to parent. |

`booking_status_history` unchanged — still keyed to `booking.id` (env-level), records per-env transitions.

### New: `booking_conflict_ack`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `tenant_id` | int FK | |
| `booking_id` | int FK | The env booking being acknowledged *from* (owner's side). |
| `other_booking_id` | int FK | The conflicting env booking. |
| `willing_to_share` | bool, nullable | `null` = not yet acknowledged. |
| `notes` | text, nullable | Coordination text (account ranges, perf testing warnings, etc.). |
| `acknowledged_by` | int FK user, nullable | Owner or delegate. |
| `acknowledged_at` | datetime, nullable | |
| `created_at`, `updated_at` | datetime | |

Unique constraint on `(booking_id, other_booking_id)`. Rows are created lazily on first acknowledgement — absence of a row = "not yet acknowledged."

### Conflict computation

Conflicts are **not stored** — they're computed on read:

> Any two `booking` rows with the same `environment_id`, overlapping `[start_date, end_date)` windows, and neither in a lifecycle-defined terminal state (initially `rejected` and `closed` — if a lifecycle template adds more, they're treated the same way), are in conflict.

`has_unacknowledged_conflicts` for a given env booking = `true` when at least one conflict pair has no `booking_conflict_ack` row where `booking_id = me` and `willing_to_share IS NOT NULL`. Derived at list/detail fetch time.

## API

### New — `/api/v1/booking-requests`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/booking-requests` | Create request + N children. Body: shared fields + `environment_ids: int[]` + `delegate_user_ids: int[]`. Conflicts are **soft** — creation always succeeds (subject to normal validation). Response includes a `detected_conflicts` field listing each child's overlaps so the form can surface them immediately; these also show up via the normal conflict indicator afterwards. |
| `GET` | `/booking-requests/preview-conflicts` | Given `{environment_ids, start_date, end_date}`, returns per-env conflict lists without creating anything. Used by `BookingForm` to show conflicts before submit so the user can adjust if they want. |
| `GET` | `/booking-requests` | List requests for tenant. Filters: `booked_by`, date range, rollup status. Rollup is derived per request from its children: `all_approved` if every child is in `approved`; `all_rejected` if every child is `rejected`; `mixed` if terminal states differ; else the common non-terminal state (e.g., `submitted`, `draft`). Always computed on read — never stored. |
| `GET` | `/booking-requests/{id}` | Request detail with children + permissions. |
| `PATCH` | `/booking-requests/{id}/standard-fields` | Edit shared fields: `project_name`, `booking_type_id`, `start_date`, `end_date`, `notes`, `context_tag`, `exclusive_use_requested`, `delegate_user_ids`. Permission-gated via lifecycle template's standard-field permissions (existing pattern). |
| `PATCH` | `/booking-requests/{id}/custom-fields` | Edit request-level custom fields. Same permission gating. |
| `POST` | `/booking-requests/{id}/environments` | Add env to existing request — creates child booking in lifecycle's initial state. Body: `{environment_id, start_date?, end_date?}` (overrides optional; defaults to parent window). |
| `DELETE` | `/booking-requests/{id}/environments/{booking_id}` | Soft-delete child env booking. |

### Changed — `/api/v1/bookings`

| Method | Path | Change |
|---|---|---|
| `GET` | `/bookings` | Unchanged shape; gains optional `booking_request_id` filter. Response rows denormalize `project_name`, `booked_by_username`, `booking_type_id` from parent for list display, and include `has_unacknowledged_conflicts: bool`. |
| `GET` | `/bookings/{id}` | Response adds a `request` block with parent fields and `has_unacknowledged_conflicts`. |
| `POST` | `/bookings/{id}/transition` | Unchanged. |
| `GET` | `/bookings/{id}/allowed-transitions` | Unchanged. |
| `GET` | `/bookings/{id}/history` | Unchanged. |
| `PATCH` | `/bookings/{id}/standard-fields` | **Narrowed** — only env-specific overrides (`start_date`, `end_date`). All other standard fields moved to the request endpoint. |
| `PATCH` | `/bookings/{id}/custom-fields` | **Removed** — custom fields now live on the request. |
| `POST` | `/bookings/{id}/approve`, `/reject`, `/cancel` | **Removed** — replaced by `/transition`. |

### New — conflict endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/bookings/{id}/conflicts` | Returns `[{other_booking: summary, ack: {willing_to_share, notes, acknowledged_at, acknowledged_by} \| null}, ...]`. |
| `PUT` | `/bookings/{id}/conflicts/{other_id}/ack` | Upsert the ack row for `(booking_id, other_booking_id)`. Body: `{willing_to_share: bool, notes?: str}`. **Authorization**: current user is `booked_by` of the booking's parent request OR listed in `delegate_user_ids`. |

### Events (outbox pattern)

New: `BookingRequestCreated`, `BookingRequestUpdated`, `BookingEnvironmentAdded`, `BookingEnvironmentRemoved`, `BookingConflictAcknowledged`. Existing `BookingStatusChanged` unchanged (per-env).

## Frontend

### Routing

Single canonical detail page at `/bookings/:id` (per env). The page surfaces the request context alongside the env's own state, so no separate `/booking-requests/:id` page is needed. List rows and calendar events link here.

### New components — `frontend/src/components/bookings/`

| Component | Purpose |
|---|---|
| `TransitionButtons.tsx` | Extracted from `BookingDetail.tsx:183-203`. Renders action buttons from `allowedTransitions`. Reused on detail page + calendar drawer + `EnvironmentsPanel` rows. |
| `EditStandardFieldsDialog.tsx` | Extracted. Edits **request-level** shared fields. |
| `EditCustomFieldsDialog.tsx` | Extracted. Edits **request-level** custom fields. |
| `EditEnvOverridesDialog.tsx` | Edits one env booking's date overrides (`start_date`, `end_date`) only. |
| `EnvironmentsPanel.tsx` | Table of all envs in a request: env name, dates, status chip, per-env `TransitionButtons`, remove button, "Add environment" action. |
| `ConflictsPanel.tsx` | For a given env booking: list of conflicts + ack form per conflict (willing_to_share toggle + notes + save). Form disabled unless current user is owner or delegate. |
| `ConflictIndicator.tsx` | Small badge (e.g., `WarningIcon` with tooltip "N unacknowledged conflicts"). Used in list column and detail breadcrumb. |
| `EnvironmentPicker.tsx` | Multi-select chip input for `BookingForm`. |

### Changed pages

- **`BookingForm.tsx`** — replaces single env select with `EnvironmentPicker`; adds delegate users multi-select; renames `exclusive_use` → `exclusive_use_requested`. As the user picks envs / dates, the form calls `GET /booking-requests/preview-conflicts` (debounced) and shows detected conflicts inline ("Env B has 2 existing bookings in this window") so the user can decide to proceed or adjust. POSTs to `/booking-requests`; creation always succeeds on validation pass. After create, the user lands on the new request's detail page where conflicts appear with unacked indicators.
- **`BookingList.tsx`** — one row per env booking (R1). Columns: Project (denormalized, links to `/bookings/:id`), Environment, Booked By, Start, End, Type, Status, **Conflicts** (`ConflictIndicator`), **Actions** (kebab `IconButton`: "Open" + dynamic transitions, lazy-loaded via `getAllowedTransitions` on menu open, cached per row). Remove `checkboxSelection`, bulk action bar, `handleBulkApprove` / `handleBulkReject`.
- **`BookingCalendar.tsx`** — one event per env, title format `"{project} — {env}"`. Drawer stays compact: read-only request summary, this env's status + `TransitionButtons`, conflict count + link to "Resolve conflicts" on detail page, "View full details" link → `/bookings/:id`. Remove `handleApprove` / `handleReject` / `handleCancel` and `canApproveReject` / `canCancel`. Editing happens on the detail page.
- **`BookingDetail.tsx`** — restructured:
  1. Breadcrumb / header with request title, booked_by, `ConflictIndicator`.
  2. Request section — shared fields read-only, Edit button opens `EditStandardFieldsDialog`.
  3. `EnvironmentsPanel` — all envs in the request, this one highlighted; each row has its own `TransitionButtons` and "Remove" button.
  4. This env's section — status chip, date overrides display + Edit via `EditEnvOverridesDialog`, `ConflictsPanel`.
  5. Custom fields (request-level) — display + Edit via `EditCustomFieldsDialog`.
  6. History (env-level) — unchanged.

### Store / services

- **New `bookingRequestSlice.ts`** + `bookingRequestService.ts`. Thunks: `fetchBookingRequests`, `fetchBookingRequest`, `createBookingRequest`, `addEnvironment`, `removeEnvironment`, `updateRequestStandardFields`, `updateRequestCustomFields`.
- **`bookingSlice.ts`** — remove `approveBooking` / `rejectBooking` / `cancelBooking` thunks; add `fetchConflicts`, `acknowledgeConflict`.
- **`bookingService.ts`** — remove `approveBooking` / `rejectBooking` / `cancelBooking`; narrow `updateStandardFields` to env overrides only; remove `updateCustomFields`; add `getConflicts`, `acknowledgeConflict`.

## Testing

### Backend

- `booking_request_service`
  - Create with N envs — happy path, duplicate envs rejected, non-existent env rejected.
  - Create with overlapping existing bookings succeeds; response's `detected_conflicts` lists them per env.
  - `preview-conflicts` returns the same shape as `detected_conflicts` without side effects.
  - Add / remove env on existing request; dates default from parent; override accepted.
- `conflict_service`
  - Overlap detection: inclusive/exclusive bounds, same-env-only, terminal states excluded (`rejected`, `closed`).
  - `has_unacknowledged_conflicts` derivation — `null` ack counts as unacknowledged.
- `booking_conflict_ack` authorization
  - Owner can ack; listed delegate can ack; other users get 403.
- `booking_lifecycle_service`
  - Per-env transition on one child does not affect siblings.
  - Allowed transitions look up via parent's `booking_type_id` → lifecycle template.

### Frontend

Manual (per CLAUDE.md's no-framework stance on UI):

- Create request with multi-select envs → all children appear in list.
- Create with conflicting env → form shows inline conflict preview; user proceeds; both the new booking and the existing conflicting booking surface unacknowledged-conflict indicators in the list.
- From list, kebab on a row shows transitions for that env only; approving env A doesn't affect env B of the same request.
- Conflict indicator appears on list rows with unacked conflicts; acking via detail page clears the indicator.
- Delegate user can acknowledge on owner's behalf; non-delegate gets a disabled form.
- Calendar event per env; drawer shows correct per-env state; "View full details" navigates correctly.

## Migration

Two-step, deploy-safe:

1. **Step 1** — add `booking_request` table, add `booking_conflict_ack` table, add `booking.booking_request_id` column (nullable). Backfill: one parent row per existing booking, copying shared fields. Service layer dual-reads (prefer parent when present) during the transition. Old and new columns coexist.
2. **Step 2** (follow-up migration, after Step 1 is deployed and all code reads from parent) — set `booking.booking_request_id` NOT NULL, drop the moved columns (`project_name`, `booking_type_id`, `notes`, `exclusive_use`, `context_tag`, `custom_fields`, `booked_by`).

Migrations written manually (per CLAUDE.md — no `--autogenerate`). Enum columns on the new parent use `native_enum=False`.

## Deletions (consolidated)

- Backend routes: `POST /bookings/{id}/approve`, `/reject`, `/cancel` and their service functions.
- Backend columns (Step 2): `booking.project_name`, `booking.booking_type_id`, `booking.notes`, `booking.exclusive_use`, `booking.context_tag`, `booking.custom_fields`, `booking.booked_by`.
- Frontend: `bookingService.approveBooking` / `rejectBooking` / `cancelBooking`; matching `bookingSlice` thunks; `bookingService.updateCustomFields`; `BookingList` bulk-selection state + handlers; `BookingCalendar` approve/reject/cancel handlers and `canApproveReject` / `canCancel` helpers.

## Implementation phasing (guidance for plan)

The implementation plan will break into reviewable chunks, but the natural order is:

1. Backend data model + migration Step 1.
2. Backend services — `booking_request_service`, `conflict_service`; dual-read shim in existing booking service.
3. Backend API — new request endpoints, conflict endpoints, narrow existing booking endpoints.
4. Frontend shared component extraction (`TransitionButtons`, dialog extraction) — behaviour-preserving refactor.
5. Frontend store / services — `bookingRequestSlice`, `bookingRequestService`; updated `bookingSlice` / `bookingService`.
6. Frontend UI — `BookingForm` multi-select, `BookingList` inline kebab + conflict indicator, `BookingCalendar` drawer, `BookingDetail` refactor.
7. Cleanup — remove `/approve` `/reject` `/cancel` routes + legacy thunks; run migration Step 2.

Steps 1–4 can ship together (backward compatible). 5–6 flip the UI to the new endpoints. 7 is the tear-out once 5–6 are deployed.
