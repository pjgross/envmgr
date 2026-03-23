export type BookingType = 'shared' | 'exclusive';
export type BookingStatus = 'pending' | 'approved' | 'rejected';
export type ContextTag = 'deployment' | 'regression' | 'none';

export interface BookingResponse {
  id: number;
  environment_id: number;
  environment_name: string | null;
  project_name: string;
  booked_by: number;
  booked_by_username: string | null;
  start_date: string;
  end_date: string;
  booking_type: BookingType;
  status: BookingStatus;
  notes: string | null;
  recurrence_rule: string | null;
  recurrence_parent_id: number | null;
  release_id: number | null;
  test_phase_id: number | null;
  context_tag: ContextTag;
  tenant_id: number;
  created_at: string;
  updated_at: string;
}

export interface BookingCreate {
  environment_id: number;
  project_name: string;
  start_date: string; // ISO datetime string
  end_date: string;
  booking_type: BookingType;
  notes?: string;
  recurrence_rule?: string;
  release_id?: number;
  test_phase_id?: number;
  context_tag?: ContextTag;
  custom_fields?: Record<string, unknown>;
}

export interface BookingCreateResponse {
  booking: BookingResponse;
  overlap_warnings: number[];
}
