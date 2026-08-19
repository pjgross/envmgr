import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { contentionForecastService } from '../services/contentionForecastService';
import { formatApiError } from '../services/apiError';
import type { ContentionHorizon } from '../types/contentionForecast';

interface ContentionForecastSliceState {
  // The leading-indicator count for whichever window was last requested —
  // "N contentions in the next `weeks` weeks". `weeks` travels alongside
  // `count` rather than being assumed from whatever the caller last asked
  // for: the server echoes it back, so a stale in-flight request cannot
  // leave the count and the window it describes out of step.
  count: number | null;
  weeks: number | null;
  loading: boolean;
  error: string | null;
  // Guards against a same-slot race: this thunk carries no sequencing of its
  // own, and ContentionHorizon dispatches it again on every horizon change
  // with no cancellation of whatever was already in flight. Rapid switching
  // (e.g. 2 -> 26 weeks) can let the OLDER request resolve after the newer
  // one, and applying it would leave `weeks` describing the outgoing
  // selection while the URL already shows the new one — the mismatch
  // `ContentionHorizon`'s `fetchedWeeks === weeks` guard uses to withhold a
  // stale-labelled count would then never clear, since nothing re-dispatches
  // just because `weeks` (the URL's, unchanged) is still the same value.
  // Same pattern and same reason as `environmentGroupSlice`'s
  // `environmentGroupsRequestId`: set to the dispatching action's
  // `meta.requestId` on `pending`; `fulfilled`/`rejected` ignore any
  // response whose requestId is no longer the latest one for this slot.
  currentRequestId: string | null;
}

const initialState: ContentionForecastSliceState = {
  count: null,
  weeks: null,
  loading: false,
  error: null,
  currentRequestId: null,
};

// `rejectWithValue(formatApiError(...))`, not an escaping error. Redux
// Toolkit's default `miniSerializeError` copies only
// name/message/stack/code — `response.data.detail`, where the backend puts
// its reason, is dropped, and a real AxiosError's `.message` is the generic
// "Request failed with status code 422". Every caller reads
// `result.payload` / `state.error`, never `result.error.message`. See
// CLAUDE.md's note on BookingTypesPanel / ComponentTypesPanel /
// LifecycleTemplatesPanel / decommissionSlice, the earlier conversions for
// exactly this gap.
export const fetchContentionHorizon = createAsyncThunk<
  ContentionHorizon,
  number,
  { rejectValue: string }
>('contentionForecast/fetchHorizon', async (weeks, { rejectWithValue }) => {
  try {
    return await contentionForecastService.getHorizon(weeks);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the contention forecast'));
  }
});

const contentionForecastSlice = createSlice({
  name: 'contentionForecast',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchContentionHorizon.pending, (state, action) => {
        // Recorded so fulfilled/rejected below can tell a stale response
        // from the current one — see the field's docblock above.
        state.currentRequestId = action.meta.requestId;
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchContentionHorizon.fulfilled, (state, action) => {
        // A response for a request that is no longer the latest one
        // dispatched (a later horizon change fired before this one landed)
        // is discarded rather than applied — applying it would strand the
        // component under a `weeks` value the URL no longer selects.
        if (action.meta.requestId !== state.currentRequestId) return;
        state.loading = false;
        state.count = action.payload.count;
        state.weeks = action.payload.weeks;
      })
      .addCase(fetchContentionHorizon.rejected, (state, action) => {
        if (action.meta.requestId !== state.currentRequestId) return;
        state.loading = false;
        state.error = action.payload ?? 'Failed to load the contention forecast';
      });
  },
});

export default contentionForecastSlice.reducer;
