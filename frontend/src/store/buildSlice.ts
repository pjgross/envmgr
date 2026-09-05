// frontend/src/store/buildSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { buildService } from '../services/buildService';
import { formatApiError } from '../services/apiError';
import type { Build, BuildFilters } from '../types/build';

interface BuildState {
  items: Build[];
  total: number;
  current: Build | null;
  loading: boolean;
  /**
   * The list query's own flag. `loading` is shared by the other thunks, and
   * an aborted list request on unmount has no successor to clear it —
   * isolating the list keeps that from hanging every other consumer of the
   * slice.
   */
  listLoading: boolean;
  error: string | null;
}

const initialState: BuildState = {
  items: [],
  total: 0,
  current: null,
  loading: false,
  listLoading: false,
  error: null,
};

export const fetchBuilds = createAsyncThunk(
  'build/fetch',
  async (filters: BuildFilters | undefined, { rejectWithValue }) => {
    try {
      return await buildService.list(filters);
    } catch (err) {
      // RTK's default serializer drops response.data.detail — format it here
      // or the page renders an HTTP status line instead of the reason.
      return rejectWithValue(formatApiError(err, 'Failed to load builds'));
    }
  },
);
export const fetchBuildById = createAsyncThunk('build/fetchById', (id: number) =>
  buildService.get(id),
);

const slice = createSlice({
  name: 'build',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchBuilds.pending, (s) => { s.listLoading = true; s.error = null; });
    b.addCase(fetchBuilds.fulfilled, (s, a) => {
      s.listLoading = false;
      s.items = a.payload.rows;
      s.total = a.payload.total;
    });
    b.addCase(fetchBuilds.rejected, (s, a) => {
      // useServerGrid aborts a superseded request rather than ignoring its
      // reply. RTK dispatches `pending` for the new request synchronously,
      // then `rejected` for the aborted one on a microtask — without this
      // guard the spinner flickers off and `error` is set to 'Aborted'
      // while the real request is still in flight. `.abort()` marks
      // meta.aborted itself, independently of rejectWithValue, so the guard
      // still fires for an aborted request.
      if (a.meta.aborted) return;
      s.listLoading = false;
      s.error = (a.payload as string | undefined) ?? a.error.message ?? 'Failed to load builds';
    });
    b.addCase(fetchBuildById.fulfilled, (s, a) => { s.current = a.payload; });
  },
});

export default slice.reducer;
