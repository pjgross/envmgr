import type { AgreementGapAckRead } from './agreementGap';

export type BookingStatus = string; // lifecycle state key e.g. 'draft', 'submitted', 'approved'
export type ContextTag = 'deployment' | 'regression' | 'none';

export interface CustomFieldPermission {
  visible: boolean;
  editable: boolean;
}

export interface BookingResponse {
  id: number;
  environment_id: number;
  environment_name: string | null;
  project_name: string;
  // The project this booking's parent request links to — id plus a
  // batch-resolved display name. Distinct from project_name above, which is
  // the free-text "Purpose" field on the same booking_request; the two must
  // never be conflated.
  project_id: number | null;
  project_name_link: string | null;
  booked_by: number;
  booked_by_username: string | null;
  start_date: string;
  end_date: string;
  booking_type_id: number;
  exclusive_use: boolean;
  status: BookingStatus;
  notes: string | null;
  recurrence_rule: string | null;
  recurrence_parent_id: number | null;
  release_id: number | null;
  test_phase_id: number | null;
  context_tag: ContextTag;
  custom_fields: Record<string, unknown> | null;
  custom_field_permissions?: Record<string, CustomFieldPermission>;
  standard_field_permissions?: Record<string, { editable: boolean }>;
  tenant_id: number;
  created_at: string;
  updated_at: string;
  // Required since 2026-08-08: `bookings.py::_to_response` now takes it
  // required-positional and every one of its six callers supplies it from a
  // batched lookup. Four of those six used to assign nothing, so this arrived
  // as `false` on four endpoints regardless of the truth.
  has_unacknowledged_conflicts: boolean;
  booking_request_id?: number | null;
  // A3's usage-agreement warning: the message, and whether anyone has
  // accepted it. Computed from usage_agreement, never stored — the backend
  // always sends both (see BookingResponse's required-positional `gap`
  // guard in bookings.py), so these are required here rather than optional:
  // an optional type would let a fixture claim "no gap data available" when
  // the wire contract guarantees the opposite. A3 WARNS: neither field
  // refuses or alters a booking.
  agreement_gap: string | null;
  has_unacknowledged_agreement_gap: boolean;
  // WHO accepted the gap and WHEN — carried by `GET /bookings/{id}` alone
  // (detail-page information; a paginated list would need a batch lookup for
  // something no row renders).
  //
  // DETAIL-ONLY IN VALUE, NOT IN KEY. No route sets
  // `response_model_exclude_unset`, so FastAPI serialises `agreement_gap_ack`
  // on EVERY BookingResponse — the list, the PATCH, the transition all send
  // `"agreement_gap_ack": null`. There is therefore NO absent-key-vs-null
  // distinction on the wire, and nothing may key on one: absence and null both
  // mean "no acknowledgement to show here" and collapse with `?? null`. The
  // `?` is TypeScript slack for fixtures, not a signal. If you need the ack,
  // re-read the detail — do not infer it from a non-detail response (that
  // inference is exactly review finding I1).
  agreement_gap_ack?: AgreementGapAckRead | null;
  // Provenance, not a live link — set for a booking that arrived via an
  // environment group, null for a hand-picked environment.
  environment_group_id: number | null;
  environment_group_name: string | null;
  request?: {
    id: number;
    project_name: string;
    booking_type_id: number;
    booked_by: number;
    booked_by_username?: string;
    delegate_user_ids: number[] | null;
  } | null;
}

export interface BookingCreate {
  environment_id: number;
  project_name: string;
  start_date: string; // ISO datetime string
  end_date: string;
  booking_type_id: number;
  exclusive_use?: boolean;
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
