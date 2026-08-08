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
  // The author's NAME, sent with the row (backend: `_ack_read`, which resolves
  // it with a lookup that is deliberately NOT tenant-qualified — under
  // master-admin impersonation the acknowledger can legitimately sit outside
  // the ack's tenant). Required, because both sources of this type — the ack
  // PUT and `GET /bookings/{id}`'s `agreement_gap_ack` — always send it.
  //
  // Nullable in VALUE: an author whose user row no longer resolves has no name,
  // and the panel then renders "Acknowledged on <when>". It must NEVER fall
  // back to `acknowledged_by`, which is an id.
  acknowledged_by_username: string | null;
}
