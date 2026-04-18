# Received Conflict Feedback — Design

**Date**: 2026-04-18
**Status**: Draft for review
**Area**: Bookings → Conflicts panel (frontend + backend)

## Problem

The booking detail page has a `ConflictsPanel` that lets a booking's owner (or a delegate) post feedback — `willing_to_share` + free-text `notes` — on each other booking that overlaps with theirs. There is today no way for the booking owner to **see the feedback that other bookings' owners have posted about *their* booking**. That information is already stored (every ack row has a `booking_id` and an `other_booking_id`, so the inverse lookup is cheap); it just isn't surfaced.

## Goals

- Booking owner (and any other authenticated tenant user) can see a read-only list of feedback left by counterparties about this booking.
- Existing editable feedback flow is preserved without regression.
- The booking detail page does not get noticeably longer when there is little or no feedback activity.

## Non-goals

- Live updates / push notifications when someone posts feedback.
- Editing another user's feedback.
- Aggregating feedback across a user's bookings on a dashboard.

## User experience

The existing `ConflictsPanel` on the booking detail page gains a `Tabs` header with two tabs:

1. **"Your feedback" (`N`)** — existing editable list, unchanged. Editable only when the viewer is the booking's owner or a delegate (`canAcknowledge=true`); read-only for everyone else.
2. **"Feedback received" (`M`)** — new read-only list. Visible to any authenticated tenant user viewing the page, so that people researching their own bookings can see how overlaps are currently being negotiated.

The panel's outer container renders when **either** list is non-empty: `conflicts.length > 0 || receivedFeedback.length > 0`. If only one tab has content, the empty tab shows a subtle line ("No feedback received yet." / "No conflicts for this booking.") rather than a blank area.

Each row in Tab 2 shows, in a compact card:

```
Booking #42 · 2026-04-20 → 2026-04-24 · status: booked
Project: "Payments rewrite"   Booked by: alice (alice@example.com)
────
Willing to share: Yes / No / (not yet answered)
"We'd prefer exclusive access Mon–Tue, happy to share Wed+"
— bob, 2026-04-18 10:32
```

The booking number is a link to `/bookings/{id}` for drill-through. No edit controls, no save button.

## Backend

### New endpoint

`GET /bookings/{booking_id}/received-feedback` → `list[ReceivedFeedbackItem]`

- Auth: `get_current_user` (any authenticated user of the tenant).
- Filters: `tenant_id == current_user.active_tenant_id`, `other_booking_id == booking_id`.
- Excludes rows where **both** `willing_to_share IS NULL` and `notes IS NULL/empty` (no actual feedback posted yet — just a placeholder row).
- Order: `acknowledged_at DESC`.

### Response schema

Defined in `backend/app/api/v1/schemas/conflict.py`:

```python
class UserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    email: str


class RequestContextRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_name: str
    notes: Optional[str] = None
    context_tag: str
    exclusive_use_requested: bool
    booked_by: UserRef


class ReceivedFeedbackItem(BaseModel):
    willing_to_share: Optional[bool]
    notes: Optional[str]
    acknowledged_at: datetime
    acknowledged_by: UserRef

    source_booking: EnvBookingSummary   # the conflicting booking whose owner posted the feedback
    source_request: RequestContextRef   # its parent BookingRequest
```

`EnvBookingSummary` is reused from `backend/app/api/v1/schemas/booking_request.py`.

### Service layer

New function in `backend/app/services/conflict_service.py`:

```python
async def list_received_feedback(
    db: AsyncSession, booking_id: int, tenant_id: int
) -> list[ReceivedFeedbackRow]
```

Implementation:

- Single `select` joining `booking_conflict_ack` ⋈ `booking` (on `booking_conflict_ack.booking_id`) ⋈ `booking_request` (on `booking.booking_request_id`) ⋈ `user` twice — once for `acknowledged_by`, once for `booking_request.booked_by`.
- Filter by `other_booking_id == booking_id`, `tenant_id`, and the non-empty-row predicate.
- Return typed rows the API layer can map into `ReceivedFeedbackItem`.

No new tables, no migration.

### API wiring

Add handler to `backend/app/api/v1/conflicts.py`:

```python
@router.get("/{booking_id}/received-feedback", response_model=list[ReceivedFeedbackItem])
async def list_received_feedback(
    booking_id: int,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    ...
```

Errors: tenant isolation is implicit via the `tenant_id` filter; a booking in another tenant simply returns an empty list. No explicit 404 (the existing `/conflicts` endpoint also returns `[]` for terminal/missing bookings, so this matches).

## Frontend

### Types

`frontend/src/types/conflict.ts` gains:

```ts
export type UserRef = { id: number; username: string; email: string }

export type RequestContextRef = {
  id: number
  project_name: string
  notes: string | null
  context_tag: string
  exclusive_use_requested: boolean
  booked_by: UserRef
}

export type ReceivedFeedbackItem = {
  willing_to_share: boolean | null
  notes: string | null
  acknowledged_at: string
  acknowledged_by: UserRef
  source_booking: EnvBookingSummary
  source_request: RequestContextRef
}
```

### Service

`frontend/src/services/bookingService.ts` gains:

```ts
getReceivedFeedback: (id: number): Promise<ReceivedFeedbackItem[]> =>
  api.get(`/bookings/${id}/received-feedback`).then((r) => r.data),
```

### Components

- `ConflictsPanel.tsx` is restructured:
  - Keeps its outer `<Paper>` and title.
  - Adds `<Tabs>` header with two tabs and item counts.
  - Tab 1 renders the existing body unchanged.
  - Tab 2 renders a new child component `ReceivedFeedbackList`.
- `ReceivedFeedbackList.tsx` (new, same folder): takes `items: ReceivedFeedbackItem[]` and renders the read-only cards.

### Data flow

`ConflictsPanel` fetches both lists in parallel on mount and whenever `bookingId` changes:

```ts
const [conflicts, received] = await Promise.all([
  bookingService.getConflicts(bookingId),
  bookingService.getReceivedFeedback(bookingId),
])
```

Separate `useState` slices for each list so an error in one tab does not clear the other. Each tab has its own inline `<Alert severity="error">` driven by `formatApiError`.

### Mutations

The existing `saveAck` currently calls `load()` to refresh conflicts. That becomes `reload()` which refreshes both lists in parallel — the counterparty may have posted feedback about us since the page rendered.

### Visibility & permission

- Outer panel: rendered when either list is non-empty.
- Tab 1 edit controls: unchanged — gated by `canAcknowledge`.
- Tab 2: readable by any authenticated tenant user; no edit controls at any auth level.

### Out of scope

- Polling / NATS subscription / websocket for live updates.
- Cancellation of in-flight requests on unmount (React 18 handles the no-op gracefully; matches existing codebase patterns).

## Testing

### Backend

In `backend/tests/api/test_conflicts.py` (extend existing file):

- `test_received_feedback_returns_acks_targeting_this_booking` — two conflicting bookings, counterparty posts an ack, GET returns the row with correct attribution and project context.
- `test_received_feedback_excludes_empty_rows` — row with `willing_to_share=None` and `notes=None` is not returned.
- `test_received_feedback_tenant_isolation` — ack created in tenant A is not returned to a user in tenant B.
- `test_received_feedback_includes_source_request_context` — `project_name`, `booked_by.username`, `context_tag`, `exclusive_use_requested` populated from the joined `BookingRequest` + `User`.
- `test_received_feedback_ordered_by_acknowledged_at_desc` — two acks at different times, newer one appears first.

In `backend/tests/services/test_conflict_service.py`:

- Unit test `list_received_feedback` directly: seeded DB with matching/non-matching ack rows, assert filter and join results.

### Frontend

`frontend/src/components/bookings/__tests__/ConflictsPanel.test.tsx` (create if absent, matching existing test patterns):

- Renders both tabs with item counts.
- Tab 2 renders read-only — no save button, willing-to-share rendered as text, not a checkbox input.
- Panel hidden when both lists empty; shown when only received feedback has content.
- "No feedback received yet." empty state shown inside Tab 2 when appropriate.
- Error loading Tab 2 does not clear Tab 1 content.
- Clicking the booking number in a received-feedback row navigates to `/bookings/{id}`.

### Manual

Per CLAUDE.md UI-change requirement: start the dev stack, create two overlapping bookings as two users, post feedback from each side, confirm each owner sees their own edits in Tab 1 and the counterparty's feedback in Tab 2 of their respective booking detail pages.

## Files touched (summary)

- `backend/app/api/v1/conflicts.py` — new handler.
- `backend/app/api/v1/schemas/conflict.py` — new schemas.
- `backend/app/services/conflict_service.py` — new `list_received_feedback`.
- `backend/tests/api/test_conflicts.py` — new tests.
- `backend/tests/services/test_conflict_service.py` — new tests.
- `frontend/src/types/conflict.ts` — new types.
- `frontend/src/services/bookingService.ts` — new method.
- `frontend/src/components/bookings/ConflictsPanel.tsx` — add tabs, parallel fetch, reload.
- `frontend/src/components/bookings/ReceivedFeedbackList.tsx` — new component.
- `frontend/src/components/bookings/__tests__/ConflictsPanel.test.tsx` — new / updated tests.
