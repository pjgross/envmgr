// frontend/src/store/buildSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { buildService } from '../services/buildService';
import type { Build, BuildFilters } from '../types/build';

interface BuildState {
  items: Build[];
  current: Build | null;
  loading: boolean;
  error: string | null;
}

const initialState: BuildState = {
  items: [],
  current: null,
  loading: false,
  error: null,
};

export const fetchBuilds = createAsyncThunk('build/fetch', (filters?: BuildFilters) =>
  buildService.list(filters),
);
export const fetchBuildById = createAsyncThunk('build/fetchById', (id: number) =>
  buildService.get(id),
);

const slice = createSlice({
  name: 'build',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchBuilds.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchBuilds.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchBuilds.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load builds';
    });
    b.addCase(fetchBuildById.fulfilled, (s, a) => { s.current = a.payload; });
  },
});

export default slice.reducer;
