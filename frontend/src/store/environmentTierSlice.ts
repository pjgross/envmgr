import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentTierService } from '../services/environmentTierService';
import { formatApiError } from '../services/apiError';
import type {
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  EnvironmentTierUpdate,
} from '../types/environmentTier';
import type { Paged } from '../types/pagination';

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

const sortTiers = (tiers: EnvironmentTierResponse[]): EnvironmentTierResponse[] =>
  [...tiers].sort((a, b) => a.display_order - b.display_order || a.id - b.id);

export const fetchEnvironmentTiers = createAsyncThunk<
  Paged<EnvironmentTierResponse>,
  void,
  { rejectValue: string }
>('environmentTier/fetch', async (_, { rejectWithValue }) => {
  try {
    return await environmentTierService.listTiers();
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load tiers'));
  }
});

export const createEnvironmentTier = createAsyncThunk<
  EnvironmentTierResponse,
  EnvironmentTierCreate,
  { rejectValue: string }
>('environmentTier/create', async (data, { rejectWithValue }) => {
  try {
    return await environmentTierService.createTier(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create tier'));
  }
});

export const updateEnvironmentTier = createAsyncThunk<
  EnvironmentTierResponse,
  { id: number; data: EnvironmentTierUpdate },
  { rejectValue: string }
>('environmentTier/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await environmentTierService.updateTier(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update tier'));
  }
});

export const deleteEnvironmentTier = createAsyncThunk<
  number,
  number,
  { rejectValue: string }
>('environmentTier/delete', async (id, { rejectWithValue }) => {
  try {
    await environmentTierService.deleteTier(id);
    return id;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to delete tier'));
  }
});

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
        state.error = action.payload ?? action.error.message ?? 'Failed to load tiers';
      })
      .addCase(createEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = sortTiers([...state.tiers, action.payload]);
        state.total += 1;
      })
      .addCase(updateEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = sortTiers(
          state.tiers.map((t) => (t.id === action.payload.id ? action.payload : t))
        );
      })
      .addCase(deleteEnvironmentTier.fulfilled, (state, action) => {
        state.tiers = state.tiers.filter((t) => t.id !== action.payload);
        state.total -= 1;
      });
  },
});

export default environmentTierSlice.reducer;
