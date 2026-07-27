# Guided Multi-Environment Booking — book a covering set in one flow

**Date:** 2026-07-27
**Status:** Approved (design) — pending implementation plan
**Builds on:** test-env-coverage (PR #14) — launches from the coverage matrix.

## Problem

The coverage matrix (PR #14) tells the release manager which environments cover the systems the
release must test — and often a small set covers everything. But booking is still one environment
at a time through `AddPhaseBookingDialog`. The RM should be able to select several environments
(or accept the suggested covering set), pick common dates/phase/booking-type once, see conflicts
up front, and book them all in one action.

Most of the machinery already exists: `check_overlap` (per-env conflict detection),
`release_booking_service.book_environment_for_phase` (single-env release booking that sets
`release_id`/`test_phase_id` and derives the per-env `context_tag`), and
`POST /booking-requests/preview-conflicts` (read-only per-env conflict preview). What's missing is
a release-aware **bulk** path and the matrix selection UI.

## Decisions (locked)

1. **Selection:** a checkbox per environment column on the coverage matrix + **"Book selected (N)"**
   and **"Book suggested set"** (pre-checks the greedy covering set). The per-env single **Book**
   button stays.
2. **Preview then confirm:** the bulk dialog calls the existing `preview-conflicts` endpoint and
   shows per-environment conflicts before the RM confirms.
3. **Skip exclusive-blocked envs:** on confirm, book every selected environment except those with a
   hard (exclusive-use) conflict for the chosen window; report which were skipped and why.
4. **One booking per environment** (not one shared `BookingRequest`): the `context_tag` is derived
   per environment from that env's systems' release roles, which a single shared request can't
   represent. Looping the existing single-env path preserves it and reuses well-tested code.

## Backend

### Endpoint
`POST /releases/{release_id}/bookings/bulk` → `BulkBookResult`.

Request (`ReleaseBulkBookingRequest`):
```python
class ReleaseBulkBookingRequest(BaseModel):
    environment_ids: list[int] = Field(..., min_length=1)
    phase_id: Optional[int] = None
    start: datetime
    end: datetime
    booking_type_id: int
    project_name: Optional[str] = None
    notes: Optional[str] = None
    exclusive_use: bool = False
```

Response:
```python
class BulkBookCreated(BaseModel):
    environment_id: int
    booking_id: int
    warnings: list[int]      # soft-conflict (shareable) booking ids

class BulkBookSkipped(BaseModel):
    environment_id: int
    conflicts: list[int]     # exclusive-conflict booking ids

class BulkBookResult(BaseModel):
    created: list[BulkBookCreated]
    skipped: list[BulkBookSkipped]
```

### Service — `release_booking_service.bulk_book_environments(...)`
For each `environment_id` in the request (order preserved):
1. `overlap = check_overlap(db, env_id, start, end, tenant_id, exclusive_use)`.
2. If `overlap.blocked` → append to `skipped` (`conflicts = overlap.conflicts`); do **not** book.
3. Else → `booking = await book_environment_for_phase(db, release_id, phase_id, env_id, start, end, booking_type_id, tenant_id, user_id, project_name, notes, exclusive_use)` (sets release/phase/context_tag), append to `created` with `warnings = overlap.warnings`.

Because blocked envs are pre-filtered by `check_overlap`, the `book_environment_for_phase` calls
never hit the 409 path. All bookings commit atomically in the request transaction (a mid-loop
failure rolls the whole batch back — acceptable; the RM retries). Tenant scope: `_require_release`
guards the release; each `book_environment_for_phase` already validates its env/booking-type in the
tenant.

### Preview — reuse existing
The frontend calls the existing `POST /booking-requests/preview-conflicts`
(`{environment_ids, start_date, end_date}` → per-env conflict summaries). No new preview endpoint.

## Frontend

### Coverage matrix selection (`ReleaseEnvironmentCoverage.tsx`)
- Add a **checkbox** to each environment column header and a small toolbar above the table:
  **"Book selected (N)"** (disabled when N = 0) and **"Book suggested set"** (checks the env ids of
  the greedy `suggestion`, then is equivalent to Book selected).
- New prop `onBookMany: (environmentIds: number[]) => void` (the existing `onBook` single-env prop
  stays for the per-env Book button).

### Bulk dialog (`BulkBookEnvironmentsDialog.tsx`, new)
Props `{ open, onClose, releaseId, environmentIds, phases, onCreated }`.
- Lists the selected environments (names from `s.environment.environments`).
- Common fields: test phase (optional), booking type, project name, start/end date, exclusive-use,
  notes — same fields as `AddPhaseBookingDialog`.
- **Check conflicts** button → `previewConflicts({ environment_ids, start_date, end_date })`; renders
  a per-environment conflict list (soft vs exclusive), advisory.
- **Confirm** → `releaseService.bulkBookEnvironments(releaseId, payload)`; then shows a **result
  summary** ("Booked N environment(s); skipped M with exclusive conflicts: …") and calls `onCreated`
  to refresh the Gantt + bookings table. Close dismisses.

### Wiring (`ReleaseEnvironmentsTab.tsx`)
- Add `bulkEnvIds` state + a `BulkBookEnvironmentsDialog`; the coverage `onBookMany` sets
  `bulkEnvIds` and opens it. The single-env `onBook` path is unchanged.

### Types / service (`types/release.ts`, `services/releaseService.ts`)
- Add `ReleaseBulkBookingPayload`, `BulkBookResultResponse` (created/skipped) types.
- Add `releaseService.bulkBookEnvironments(releaseId, payload)` → `POST /releases/{id}/bookings/bulk`.
- Reuse `bookingRequestService.previewConflicts` if it exists; otherwise add a thin service method
  hitting `POST /booking-requests/preview-conflicts`.

## Testing

**Backend** (`tests/integration/test_release_bulk_booking_api.py`)
- Bulk-book 3 free environments → all in `created`, none skipped; each booking has `release_id`
  and (when a phase is given) `test_phase_id`; per-env `context_tag` set from the release roles.
- One environment has an existing **exclusive** booking overlapping the window → it appears in
  `skipped` with the conflicting booking id; the others are booked.
- A soft (shareable) overlap → the env is booked and its overlap id appears in `warnings`.
- Empty `environment_ids` → 422; unknown release → 404 (cross-tenant).

**Frontend** — no unit tests; verify `tsc --noEmit` + `npm run build`.

## Out of scope (follow-on)
- Grouping the batch under one shared `BookingRequest`.
- Recurring multi-env bookings.
- Conflict-acknowledgement flow from this dialog (the ack model exists; not wired here).
- Mock-aware environment selection.

## Affected files (indicative)
- `backend/app/api/v1/schemas/release_bulk_booking.py` — request/result schemas (create).
- `backend/app/services/release_booking_service.py` — `bulk_book_environments`.
- `backend/app/api/v1/releases.py` — `POST /releases/{id}/bookings/bulk` handler.
- `backend/tests/integration/test_release_bulk_booking_api.py` — bulk booking tests.
- `frontend/src/components/releases/BulkBookEnvironmentsDialog.tsx` — new dialog (create).
- `frontend/src/components/releases/ReleaseEnvironmentCoverage.tsx` — checkboxes + toolbar + `onBookMany`.
- `frontend/src/components/releases/ReleaseEnvironmentsTab.tsx` — wire the bulk dialog.
- `frontend/src/types/release.ts`, `frontend/src/services/releaseService.ts` — payload/result types + method.
