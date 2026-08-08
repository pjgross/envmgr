export type EnvBookingSummary = {
  id: number;
  environment_id: number;
  environment_name?: string | null;
  project_name?: string | null;
  start_date: string;
  end_date: string;
  status: string;
  has_unacknowledged_conflicts?: boolean;
  // A3's usage-agreement warning — see BookingResponse in booking.ts for
  // what it means. REQUIRED here, not optional/defaulted, deliberately
  // unlike has_unacknowledged_conflicts immediately above: the backend's
  // EnvBookingSummary types this the same way (no default) precisely
  // because it is constructed by keyword at six call sites across two
  // routers, and a default would let a missed one silently render "no gap"
  // for a booking that has one.
  agreement_gap: string | null;
  has_unacknowledged_agreement_gap: boolean;
  // Provenance, not a live link — set for a booking that arrived via an
  // environment group, null for a hand-picked environment.
  environment_group_id: number | null;
  environment_group_name: string | null;
};

export type BookingRequestResponse = {
  id: number;
  tenant_id: number;
  project_name: string;
  // The project this request belongs to. Distinct from `project_name`, which
  // is free text the UI labels "Purpose" — see CLAUDE.md's project_name_link
  // note. `project_name_link` is the linked Project's name, if any.
  project_id: number | null;
  project_name_link: string | null;
  booking_type_id: number;
  start_date: string;
  end_date: string;
  notes: string | null;
  context_tag: string;
  exclusive_use_requested: boolean;
  custom_fields: Record<string, unknown> | null;
  booked_by: number;
  delegate_user_ids: number[] | null;
  rollup_status: string;
  bookings: EnvBookingSummary[];
};

export type BookingRequestCreatePayload = {
  project_name: string;
  // The project this request belongs to. Distinct from `project_name` above.
  project_id?: number | null;
  booking_type_id: number;
  start_date: string;
  end_date: string;
  environment_ids: number[];
  // May be empty when environment_ids supplies at least one environment —
  // the combined "at least one environment" rule is enforced by the
  // backend service, since it spans both fields.
  environment_group_ids?: number[];
  notes?: string | null;
  context_tag?: string;
  exclusive_use_requested?: boolean;
  custom_fields?: Record<string, unknown> | null;
  delegate_user_ids?: number[] | null;
};

export type BookingRequestCreateResponse = {
  request: BookingRequestResponse;
  detected_conflicts: Record<number, EnvBookingSummary[]>;
  // `booking_id -> message` for the bookings JUST CREATED that no live usage
  // agreement covers. Keyed by booking id (not environment id, unlike
  // detected_conflicts) because the gap is a property of one booking and a
  // group booking may hold several bookings against the same environment
  // over different dates. The same text is also on each booking's own
  // `agreement_gap` in `request.bookings` — this map exists so the caller
  // doesn't have to walk that list to know whether to say anything at all.
  // Absent keys mean "no gap"; an empty map is the ordinary case.
  agreement_gaps: Record<number, string>;
};

export type PreviewConflictsResponse = {
  conflicts: Record<number, EnvBookingSummary[]>;
};
