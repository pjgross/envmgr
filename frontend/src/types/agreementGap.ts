// A3's usage-agreement gap acknowledgement — see
// backend/app/api/v1/schemas/agreement_gap.py, which this mirrors field for
// field. The gap message itself is never a type here: it is computed by the
// backend's agreement_gap_service and rendered on the booking response
// (`agreement_gap`, `has_unacknowledged_agreement_gap` — see booking.ts /
// bookingRequest.ts), so nothing here can drift from usage_agreement.
export interface AgreementGapAckRead {
  notes: string | null;
  // Non-optional, matching AgreementGapAckRead on the backend: the row
  // cannot exist without an author and a timestamp.
  acknowledged_by: number;
  acknowledged_at: string;
}
