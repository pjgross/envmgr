import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { gateTypeService } from '../services/gateTypeService';
import { formatApiError } from '../services/apiError';
import type { GateTypeResponse, GateTypeCreate, GateTypeUpdate } from '../types/gateType';
import type { Paged } from '../types/pagination';

interface GateTypeState {
  gateTypes: GateTypeResponse[];
  total: number;
  loading: boolean;
  error: string | null;
}

const initialState: GateTypeState = {
  gateTypes: [],
  total: 0,
  loading: false,
  error: null,
};

const sortGateTypes = (rows: GateTypeResponse[]): GateTypeResponse[] =>
  [...rows].sort((a, b) => a.display_order - b.display_order || a.id - b.id);

/**
 * The assignable vocabulary for a NEW selection on a gate — active types
 * only, in display order. `fetchGateTypes` loads every type regardless of
 * `is_active` (the default `include_inactive=true`), so a caller resolving
 * the NAME of a gate's already-assigned type (which may since have been
 * retired) should read `gateTypes` directly rather than this — the same
 * carve-out B3a made for a soft-deleted UserGroup still assigned to an
 * environment.
 */
export const selectActiveGateTypes = (types: GateTypeResponse[]): GateTypeResponse[] =>
  sortGateTypes(types.filter((t) => t.is_active));

export const fetchGateTypes = createAsyncThunk<
  Paged<GateTypeResponse>,
  void,
  { rejectValue: string }
>('gateType/fetch', async (_, { rejectWithValue }) => {
  try {
    return await gateTypeService.listGateTypes();
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load gate types'));
  }
});

export const createGateType = createAsyncThunk<
  GateTypeResponse,
  GateTypeCreate,
  { rejectValue: string }
>('gateType/create', async (data, { rejectWithValue }) => {
  try {
    return await gateTypeService.createGateType(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create gate type'));
  }
});

export const updateGateType = createAsyncThunk<
  GateTypeResponse,
  { id: number; data: GateTypeUpdate },
  { rejectValue: string }
>('gateType/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await gateTypeService.updateGateType(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update gate type'));
  }
});

export const deleteGateType = createAsyncThunk<
  number,
  number,
  { rejectValue: string }
>('gateType/delete', async (id, { rejectWithValue }) => {
  try {
    await gateTypeService.deleteGateType(id);
    return id;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to delete gate type'));
  }
});

const gateTypeSlice = createSlice({
  name: 'gateType',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchGateTypes.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchGateTypes.fulfilled, (state, action) => {
        state.loading = false;
        state.gateTypes = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchGateTypes.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? action.error.message ?? 'Failed to load gate types';
      })
      .addCase(createGateType.fulfilled, (state, action) => {
        state.gateTypes = sortGateTypes([...state.gateTypes, action.payload]);
        state.total += 1;
      })
      .addCase(updateGateType.fulfilled, (state, action) => {
        state.gateTypes = sortGateTypes(
          state.gateTypes.map((t) => (t.id === action.payload.id ? action.payload : t))
        );
      })
      .addCase(deleteGateType.fulfilled, (state, action) => {
        state.gateTypes = state.gateTypes.filter((t) => t.id !== action.payload);
        state.total -= 1;
      });
  },
});

export default gateTypeSlice.reducer;
