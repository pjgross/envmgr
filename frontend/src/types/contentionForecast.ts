// B6 — forward contention, folded per booking. Mirrors
// backend/app/services/contention_forecast_service.py: `STATE_UNOWNED`,
// `STATE_OWNED`, `STATE_DECIDED`. Deliberately no fourth `none` state — a
// booking with no contention is simply absent from the state map the
// backend builds, and `BookingResponse.contention_state` carries `null` for
// it, not a fourth string. See `types/booking.ts`.
export type ContentionState = 'unowned' | 'owned' | 'decided';

// GET /bookings/contention-horizon?weeks=<int> — the leading-indicator
// count: "N contentions in the next N weeks". `weeks` is echoed back by the
// server (bounded ge=1, le=104 there) so a caller can render the count next
// to the window it actually describes rather than the one it asked for.
export interface ContentionHorizon {
  count: number;
  weeks: number;
}
