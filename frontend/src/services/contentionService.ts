import api from './api';
import type {
  Escalation,
  EscalationCreate,
  EscalationDecision,
  EscalationState,
} from '../types/contention';
import type { Paged } from '../types/pagination';

// No slice thunk for escalate/decide, deliberately, matching
// bookingService.transitionState (and agreementGapService.ackGap) —  they are
// called directly from the component (Task 6). That means the component's own
// catch block must call formatApiError (services/apiError.ts) itself: there is
// no rejectWithValue/miniSerializeError boundary in front of these two calls
// to normalise the error, and no lint rule enforces it. This codebase has
// repeatedly shipped UI that shows "Request failed with status code 409"
// instead of the server's reason for exactly this shape of gap — see
// CLAUDE.md's note on BookingTypesPanel/ComponentTypesPanel.
export const contentionService = {
  escalate: (
    bookingId: number,
    otherId: number,
    body: EscalationCreate
  ): Promise<Escalation> =>
    api
      .post(`/bookings/${bookingId}/contentions/${otherId}/escalate`, body)
      .then((r) => r.data),

  decide: (escalationId: number, body: EscalationDecision): Promise<Escalation> =>
    api.put(`/contention-escalations/${escalationId}/decision`, body).then((r) => r.data),

  // `state` has deliberately no 'all' value on the wire — omission is the "no
  // selection" sentinel (see contentions.py's docstring). Do not invent one
  // here: a vocabulary containing 'all' builds byte-identical params for two
  // different filter states and the grid never refetches.
  list: (params?: {
    state?: EscalationState;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<Escalation>> =>
    api.get<Escalation[]>('/contention-escalations', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),
};
