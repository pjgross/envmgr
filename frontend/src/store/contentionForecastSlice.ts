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
}

const initialState: ContentionForecastSliceState = {
  count: null,
  weeks: null,
  loading: false,
  error: null,
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
      .addCase(fetchContentionHorizon.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchContentionHorizon.fulfilled, (state, action) => {
        state.loading = false;
        state.count = action.payload.count;
        state.weeks = action.payload.weeks;
      })
      .addCase(fetchContentionHorizon.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load the contention forecast';
      });
  },
});

export default contentionForecastSlice.reducer;
