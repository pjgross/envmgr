import api from './api';
import type { AgreementGapAckRead } from '../types/agreementGap';

// No slice thunk here, deliberately, matching bookingService.transitionState
// — the ack is called directly from the component (Task 6). That means the
// component's own catch block must call formatApiError (services/apiError.ts)
// itself: there is no rejectWithValue/miniSerializeError boundary in front of
// this call to normalise the error, and no lint rule enforces it. This
// codebase has repeatedly shipped UI that shows "Request failed with status
// code 409" instead of the server's reason for exactly this shape of gap —
// see CLAUDE.md's note on BookingTypesPanel/ComponentTypesPanel.
export const agreementGapService = {
  ackGap: (bookingId: number, notes?: string | null): Promise<AgreementGapAckRead> =>
    api
      .put(`/bookings/${bookingId}/agreement-gap/ack`, { notes: notes ?? null })
      .then((r) => r.data),
};
