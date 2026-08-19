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

  // THE STRANDING BUG. `ContentionHorizon` dispatches this thunk again on
  // every horizon change with no cancellation of whatever was already in
  // flight, and its own `fetchedWeeks === weeks` guard withholds the count
  // until a response actually describes the currently-selected window.
  // Without request-id sequencing here, a click from 2 -> 26 weeks fired
  // rapidly enough for the OLDER (2-week) response to land after the newer
  // (26-week) one would overwrite `state.weeks` back to 2 — and because
  // nothing re-dispatches just because `weeks` itself hasn't changed again,
  // the component would sit under a permanent mismatch with no error and no
  // way out but a reload. `currentRequestId` is this slice's version of
  // `environmentGroupSlice`'s `environmentGroupsRequestId` guard.
  it('an older, slower request landing after a newer one does not overwrite it', async () => {
    let resolveOlder!: (value: ContentionHorizon) => void;
    let resolveNewer!: (value: ContentionHorizon) => void;
    const olderPromise = new Promise<ContentionHorizon>((resolve) => {
      resolveOlder = resolve;
    });
    const newerPromise = new Promise<ContentionHorizon>((resolve) => {
      resolveNewer = resolve;
    });
    vi.mocked(contentionForecastService.getHorizon)
      .mockReturnValueOnce(olderPromise)
      .mockReturnValueOnce(newerPromise);

    const store = makeStore();
    // Two rapid dispatches, as two quick clicks would produce — the older
    // (2-week) request is in flight when the newer (26-week) one starts.
    const older = store.dispatch(fetchContentionHorizon(2));
    const newer = store.dispatch(fetchContentionHorizon(26));

    // Resolve OUT OF ORDER: the newer request settles first, the older one
    // arrives late — the exact race the guard exists for.
    resolveNewer({ count: 11, weeks: 26 });
    await newer;

    let state = store.getState().contentionForecast;
    expect(state.count).toBe(11);
    expect(state.weeks).toBe(26);
    expect(state.loading).toBe(false);

    resolveOlder({ count: 1, weeks: 2 });
    await older;

    // The stale response must be discarded, not applied on top of the
    // newer, already-settled one.
    state = store.getState().contentionForecast;
    expect(state.count).toBe(11);
    expect(state.weeks).toBe(26);
    expect(state.loading).toBe(false);
  });
});
