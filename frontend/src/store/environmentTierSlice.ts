import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentTierService } from '../services/environmentTierService';
import type {
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  EnvironmentTierUpdate,
} from '../types/environmentTier';

interface EnvironmentTierState {
  tiers: EnvironmentTierResponse[];
  total: number;
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentTierState = {
  tiers: [],
  total: 0,
  loading: false,
  error: null,
};

export const fetchEnvironmentTiers = createAsyncThunk(
  'environmentTier/fetch',
  () => environmentTierService.listTiers()
);

export const createEnvironmentTier = createAsyncThunk(
  'environmentTier/create',
  (data: EnvironmentTierCreate) => environmentTierService.createTier(data)
);

export const updateEnvironmentTier = createAsyncThunk(
  'environmentTier/update',
  ({ id, data }: { id: number; data: EnvironmentTierUpdate }) =>
    environmentTierService.updateTier(id, data)
);

export const deleteEnvironmentTier = createAsyncThunk(
  'environmentTier/delete',
  async (id: number) => {
    await environmentTierService.deleteTier(id);
    return id;
  }
);

const environmentTierSlice = createSlice({
  name: 'environmentTier',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchEnvironmentTiers.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchEnvironmentTiers.fulfilled, (state, action) => {
        state.loading = false;
        state.tiers = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchEnvironmentTiers.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load tiers';
      })
      .addCase(createEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = [...state.tiers, action.payload].sort(
          (a, b) => a.display_order - b.display_order || a.id - b.id
        );
        state.total += 1;
      })
      .addCase(updateEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = state.tiers.map((t) =>
          t.id === action.payload.id ? action.payload : t
        );
      })
      .addCase(deleteEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = state.tiers.filter((t) => t.id !== action.payload);
        state.total -= 1;
      });
  },
});

export default environmentTierSlice.reducer;
