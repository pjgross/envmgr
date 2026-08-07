export type EnvBookingSummary = {
  id: number;
  environment_id: number;
  environment_name?: string | null;
  project_name?: string | null;
  start_date: string;
  end_date: string;
  status: string;
  has_unacknowledged_conflicts?: boolean;
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
};

export type PreviewConflictsResponse = {
  conflicts: Record<number, EnvBookingSummary[]>;
};
