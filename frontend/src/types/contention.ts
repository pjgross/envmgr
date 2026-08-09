// A4's contention verdict and its escalation, as the API renders them. Mirrors
// backend/app/api/v1/schemas/contention.py — read that docstring before
// changing a field here, it explains why each nullable is nullable.

// Three of the four outcomes carry no winner, each with its own `reason`. Not
// a fabricated ordering — see `contention_service`'s module docstring.
export type ContentionOutcome = 'ranked' | 'no_project' | 'unranked' | 'equal_rank';

// Computed server-side from two columns and a clock, never stored — the
// browser must not re-derive it from `respond_by` alone (see `bookings_live`
// below, which is the same story for liveness).
export type EscalationState = 'open' | 'answered' | 'expired';

// One escalation record, plus the three things about it the backend computes.
// `state` and `bookings_live` are REQUIRED here for the same reason
// `EscalationRead` gives them no Pydantic default: an omitted value on this
// side would compile and silently lie to every reader, the way
// `has_unacknowledged_conflicts` did before it was made required.
export interface Escalation {
  id: number;
  booking_id: number;
  other_booking_id: number;
  owner_user_id: number;
  owner_username: string | null;
  // Who asked, beside who must answer.
  escalated_by: number;
  escalated_by_username: string | null;
  respond_by: string;
  state: EscalationState;
  bookings_live: boolean;

  decision_yields_booking_id: number | null;
  decision_notes: string | null;
  decided_by: number | null;
  decided_by_username: string | null;
  decided_at: string | null;
}

// What A4 has to say about one pair of conflicting bookings. `escalation` is
// null until someone has asked for a decision on this pair.
export interface Contention {
  outcome: ContentionOutcome;
  winner_booking_id: number | null;
  reason: string;
  escalation: Escalation | null;
}

// Body of POST /bookings/{id}/contentions/{other_id}/escalate.
export interface EscalationCreate {
  owner_user_id: number;
  respond_by: string;
}

// Body of PUT /contention-escalations/{id}/decision. A4 records this and acts
// on NOTHING — moving the yielding booking is the owning team's job, through
// the ordinary transition path.
export interface EscalationDecision {
  yields_booking_id: number;
  notes?: string | null;
}
