import { configureStore } from '@reduxjs/toolkit';
import { AxiosError } from 'axios';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import contentionForecastReducer, { fetchContentionHorizon } from '../contentionForecastSlice';
import { contentionForecastService } from '../../services/contentionForecastService';
import type { ContentionHorizon } from '../../types/contentionForecast';

vi.mock('../../services/contentionForecastService', () => ({
  contentionForecastService: {
    getHorizon: vi.fn(),
  },
}));

function makeStore() {
  return configureStore({ reducer: { contentionForecast: contentionForecastReducer } });
}

describe('contentionForecastSlice', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads the horizon count and weeks on success', async () => {
    const horizon: ContentionHorizon = { count: 4, weeks: 6 };
    vi.mocked(contentionForecastService.getHorizon).mockResolvedValueOnce(horizon);

    const store = makeStore();
    await store.dispatch(fetchContentionHorizon(6));

    const state = store.getState().contentionForecast;
    expect(state.count).toBe(4);
    expect(state.weeks).toBe(6);
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  // THE MOST IMPORTANT TEST IN THIS FILE. RTK's default miniSerializeError
  // copies only name/message/stack/code, and a real AxiosError's `.message`
  // is the generic "Request failed with status code 422" — the server's
  // reason, at response.data.detail, is dropped unless the thunk goes
  // through rejectWithValue(formatApiError(...)). A test that instead
  // rejects with a plain Error carrying the final text would pass while the
  // app is broken, which is why this constructs a real AxiosError shape.
  it('surfaces the server reason, not the HTTP status', async () => {
    const err = new AxiosError('Request failed with status code 422');
    err.response = {
      data: { detail: 'weeks must be between 1 and 104' },
      status: 422,
      statusText: 'Unprocessable Entity',
      headers: {},
      config: {} as never,
    } as never;
    vi.mocked(contentionForecastService.getHorizon).mockRejectedValueOnce(err);

    const store = makeStore();
    const result = await store.dispatch(fetchContentionHorizon(0));

    expect(fetchContentionHorizon.rejected.match(result)).toBe(true);
    expect(result.payload).toContain('weeks must be between 1 and 104');
    // Guards against a fix that surfaces SOME string but still leaks the
    // generic axios message alongside or instead of the server's reason.
    expect(result.payload).not.toContain('status code 422');

    const state = store.getState().contentionForecast;
    expect(state.error).toContain('weeks must be between 1 and 104');
    expect(state.loading).toBe(false);
  });
});
