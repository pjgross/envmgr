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

  // WHICH ARGUMENT THIS IS, in the only terms a human recognises. The worklist
  // is a list of contentions the reader has never seen, so two booking ids
  // identify nothing and `Booking #12` is exactly the `#N` fallback this
  // codebase does not render. Resolved server-side and batched by
  // `contention_service.booking_labels`, the same rule as `owner_username`
  // above: a browser-side lookup would go to a capped collection, where a name
  // past the cap is information LOST, not merely hidden.
  //
  // `booking_*` describes `booking_id` and `other_booking_*` describes
  // `other_booking_id` — the LOWER and HIGHER id, since the pair is stored
  // normalised. Neither is "mine": a worklist reader is often party to neither.
  //
  // Required-and-nullable, never optional: the server sends all four on every
  // response, and each null is a real state (a booking need not be linked to a
  // project, and a booking this tenant cannot resolve has no names at all).
  booking_environment_name: string | null;
  booking_project_name: string | null;
  other_booking_environment_name: string | null;
  other_booking_project_name: string | null;

  // WHICH SIDE IS AN A2 GROUP BOOKING, by name — part of what identifies the
  // booking, not decoration. A group booking transitions ATOMICALLY, so a
  // decision naming one member is a decision about every member: a worklist
  // that reads "Payments Rebuild on Staging gives way" about one member of a
  // five-environment group booking has described a consequence that will not
  // happen, and the worklist is where the decision is actually made.
  //
  // Null is the ordinary case — most bookings belong to no group. An ARCHIVED
  // group still arrives named (`get_group_names` deliberately does not filter
  // `deleted_at`), because its bookings still move together.
  booking_group_name: string | null;
  other_booking_group_name: string | null;

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

  // THE TWO PROJECTS BY NAME, because `winner_booking_id` on its own cannot be
  // rendered. A4's design says the line reads "Mortgage Replatform outranks
  // Payments Rebuild", and nothing else on a `ConflictItem` can supply that:
  // `other_booking.project_name` is `BookingRequest.project_name`, the free
  // text the UI labels "Purpose", NOT the linked project.
  //
  // `booking_project_name` is the SUBJECT of the request — the booking whose
  // conflicts page this is — and `other_project_name` is the row's own booking.
  // Keyed as-given, not (lower, higher): a verdict is read from one side.
  //
  // Both nullable. `no_project` is the commonest outcome in today's data, and
  // an ARCHIVED project still renders its name here beside a verdict saying the
  // link cannot be resolved — `get_project_names` deliberately does not filter
  // `deleted_at`, which is the only thing that makes that reason readable.
  booking_project_name: string | null;
  other_project_name: string | null;
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
