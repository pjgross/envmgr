import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { myWorkService } from '../services/myWorkService';
import { formatApiError } from '../services/apiError';
import type { MyWorkResponse } from '../types/myWork';

export interface MyWorkState {
  data: MyWorkResponse | null;
  loading: boolean;
  error: string | null;
}

const initialState: MyWorkState = {
  data: null,
  loading: false,
  error: null,
};

// `rejectWithValue(formatApiError(...))`, not an escaping error — Redux
// Toolkit's default `miniSerializeError` copies only
// name/message/stack/code, dropping `response.data.detail`, where the
// server's actual reason lives. See CLAUDE.md's note on BookingTypesPanel /
// ComponentTypesPanel / LifecycleTemplatesPanel / decommissionSlice, the
// earlier conversions for exactly this gap. Every caller reads
// `state.myWork.error`, never `result.error.message`.
export const fetchMyWork = createAsyncThunk<MyWorkResponse, void, { rejectValue: string }>(
  'myWork/fetch',
  async (_, { rejectWithValue }) => {
    try {
      return await myWorkService.getMyWork();
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to load your work queues'));
    }
  }
);

const myWorkSlice = createSlice({
  name: 'myWork',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchMyWork.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchMyWork.fulfilled, (state, action) => {
        state.loading = false;
        state.data = action.payload;
      })
      .addCase(fetchMyWork.rejected, (state, action) => {
        // Deliberately does NOT touch `state.data`. A transport-level
        // failure of the WHOLE `/me/work` call (the request never landed,
        // or 5xx'd before any per-queue try/except ran) must not blank out
        // whatever was last rendered — that would be strictly worse than
        // the per-queue `failed` flag this response already carries for
        // exactly this purpose.
        state.loading = false;
        state.error = action.payload ?? 'Failed to load your work queues';
      });
  },
});

/**
 * The badge total Task 7's nav reads — the sum of all five queues' counts.
 * A FAILED queue's `count` is always 0 (the schema default), so it drops out
 * of the sum on its own; nothing here needs to special-case it. Typed
 * against a minimal shape rather than `RootState` to avoid a circular import
 * with `store/index.ts`, the same call `bookingLifecycleSlice`'s selectors
 * make.
 */
export function selectMyWorkTotal(state: { myWork: MyWorkState }): number {
  const data = state.myWork.data;
  if (!data) return 0;
  return Object.values(data.queues).reduce((sum, q) => sum + q.count, 0);
}

export default myWorkSlice.reducer;
