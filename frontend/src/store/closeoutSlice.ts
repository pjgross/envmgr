import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { closeoutService } from '../services/closeoutService';
import { formatApiError } from '../services/apiError';
import type { CloseoutRead } from '../types/closeout';

interface CloseoutState {
  byRelease: Record<number, CloseoutRead>;
  loading: boolean;
  error: string | null;
}
const initialState: CloseoutState = { byRelease: {}, loading: false, error: null };

export const fetchCloseout = createAsyncThunk<CloseoutRead, number, { rejectValue: string }>(
  'closeout/fetch',
  async (releaseId, { rejectWithValue }) => {
    try { return await closeoutService.get(releaseId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load closeout')); }
  },
);

// Every write re-fetches the composite read, so the tab renders what the
// server computed rather than a local guess. Consumers read `result.payload`.
const write = (name: string, call: (releaseId: number, note?: string) => Promise<unknown>) =>
  createAsyncThunk<CloseoutRead, { releaseId: number; note?: string }, { rejectValue: string }>(
    `closeout/${name}`,
    async ({ releaseId, note }, { rejectWithValue }) => {
      try {
        await call(releaseId, note);
        return await closeoutService.get(releaseId);
      } catch (err) {
        return rejectWithValue(formatApiError(err, `Failed to ${name}`));
      }
    },
  );

export const declareStable = write('declare stable', closeoutService.declareStable);
export const withdrawStable = write('withdraw stability declaration', (id) => closeoutService.withdrawStable(id));
export const confirmHandover = write('confirm handover', closeoutService.confirmHandover);
export const withdrawHandover = write('withdraw handover', (id) => closeoutService.withdrawHandover(id));

const closeoutSlice = createSlice({
  name: 'closeout',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchCloseout.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchCloseout.fulfilled, (s, a) => { s.loading = false; s.byRelease[a.meta.arg] = a.payload; });
    b.addCase(fetchCloseout.rejected, (s, a) => { s.loading = false; s.error = a.payload ?? 'Failed to load closeout'; });
    for (const t of [declareStable, withdrawStable, confirmHandover, withdrawHandover]) {
      b.addCase(t.fulfilled, (s, a) => { s.byRelease[a.meta.arg.releaseId] = a.payload; });
    }
  },
});
export default closeoutSlice.reducer;
