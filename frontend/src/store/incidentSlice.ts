import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { incidentService } from '../services/incidentService';
import type { IncidentListRow, IncidentDetail, IncidentCreate, IncidentUpdate } from '../types/incident';

interface IncidentState {
  list: IncidentListRow[];
  detail: IncidentDetail | null;
  loading: boolean;
  error: string | null;
}

const initialState: IncidentState = {
  list: [],
  detail: null,
  loading: false,
  error: null,
};

export const fetchIncidents = createAsyncThunk(
  'incidents/list',
  (params: Record<string, unknown> = {}) => incidentService.list(params),
);

export const fetchIncident = createAsyncThunk(
  'incidents/get',
  (id: number) => incidentService.get(id),
);

export const createIncident = createAsyncThunk(
  'incidents/create',
  (data: IncidentCreate) => incidentService.create(data),
);

export const updateIncident = createAsyncThunk(
  'incidents/update',
  ({ id, data }: { id: number; data: IncidentUpdate }) => incidentService.update(id, data),
);

export const transitionIncident = createAsyncThunk(
  'incidents/transition',
  ({ id, to_state }: { id: number; to_state: string }) => incidentService.transition(id, to_state),
);

export const deleteIncident = createAsyncThunk(
  'incidents/delete',
  async (id: number) => {
    await incidentService.remove(id);
    return id;
  },
);

const incidentSlice = createSlice({
  name: 'incidents',
  initialState,
  reducers: {
    clearDetail(state) {
      state.detail = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchIncidents.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchIncidents.fulfilled, (state, action) => { state.loading = false; state.list = action.payload; })
      .addCase(fetchIncidents.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load incidents'; })

      .addCase(fetchIncident.fulfilled, (state, action) => { state.detail = action.payload; })

      .addCase(createIncident.fulfilled, (state, action) => {
        // The API returns IncidentDetail; add a minimal list row representation
        state.detail = action.payload;
      })

      .addCase(updateIncident.fulfilled, (state, action) => {
        state.detail = action.payload;
        const idx = state.list.findIndex((r) => r.id === action.payload.id);
        if (idx !== -1) {
          state.list[idx] = {
            ...state.list[idx],
            title: action.payload.title,
            severity: action.payload.severity,
            status: action.payload.status,
            detected_at: action.payload.detected_at,
            resolved_at: action.payload.resolved_at,
          };
        }
      })

      .addCase(transitionIncident.fulfilled, (state, action) => {
        state.detail = action.payload;
        const idx = state.list.findIndex((r) => r.id === action.payload.id);
        if (idx !== -1) {
          state.list[idx] = {
            ...state.list[idx],
            status: action.payload.status,
            resolved_at: action.payload.resolved_at,
          };
        }
      })

      .addCase(deleteIncident.fulfilled, (state, action) => {
        state.list = state.list.filter((r) => r.id !== action.payload);
        if (state.detail?.id === action.payload) state.detail = null;
      });
  },
});

export const { clearDetail } = incidentSlice.actions;
export default incidentSlice.reducer;
