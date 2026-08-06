import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import environmentRequestReducer, {
  fetchEnvironmentRequests,
  transitionEnvironmentRequest,
} from '../environmentRequestSlice';
import { environmentRequestService } from '../../services/environmentRequestService';

vi.mock('../../services/environmentRequestService', () => ({
  environmentRequestService: {
    listRequests: vi.fn(),
    transition: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { environmentRequest: environmentRequestReducer } });
}

describe('environmentRequestSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('stores the server total, not the row count', async () => {
    vi.mocked(environmentRequestService.listRequests).mockResolvedValue({
      rows: [{ id: 1 }] as never,
      total: 42,
    });

    const store = makeStore();
    await store.dispatch(fetchEnvironmentRequests({}));

    expect(store.getState().environmentRequest.requests).toHaveLength(1);
    expect(store.getState().environmentRequest.total).toBe(42);
  });

  it('surfaces the server reason when a transition is refused', async () => {
    // AxiosError SHAPE: generic text on .message, the real reason only at
    // response.data.detail. A plain Error carrying the final text would pass
    // against broken code, because miniSerializeError keeps .message.
    vi.mocked(environmentRequestService.transition).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 403',
      response: {
        status: 403,
        data: {
          detail:
            'Only the operating team for this environment, or an admin, can action this request',
        },
      },
    });

    const store = makeStore();
    const result = await store.dispatch(
      transitionEnvironmentRequest({ id: 1, toState: 'approved' })
    );

    expect(transitionEnvironmentRequest.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('operating team');
  });
});
