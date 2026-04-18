export type EnvBookingSummary = {
  id: number;
  environment_id: number;
  environment_name?: string;
  start_date: string;
  end_date: string;
  status: string;
  has_unacknowledged_conflicts?: boolean;
};

export type BookingRequestResponse = {
  id: number;
  tenant_id: number;
  project_name: string;
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
  booking_type_id: number;
  start_date: string;
  end_date: string;
  environment_ids: number[];
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
