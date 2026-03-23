import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { systemService } from '../services/systemService';
import type {
  SystemResponse,
  SubSystemResponse,
  SystemCreate,
  SystemUpdate,
  SubSystemCreate,
  SubSystemUpdate,
} from '../types/system';

interface SystemState {
  systems: SystemResponse[];
  currentSystem: SystemResponse | null;
  subsystems: SubSystemResponse[];
  currentSubSystem: SubSystemResponse | null;
  loading: boolean;
  error: string | null;
}

const initialState: SystemState = {
  systems: [],
  currentSystem: null,
  subsystems: [],
  currentSubSystem: null,
  loading: false,
  error: null,
};

export const fetchSystems = createAsyncThunk('system/fetchSystems', () =>
  systemService.listSystems()
);

export const fetchSystem = createAsyncThunk('system/fetchSystem', (id: number) =>
  systemService.getSystem(id)
);

export const createSystem = createAsyncThunk('system/createSystem', (data: SystemCreate) =>
  systemService.createSystem(data)
);

export const updateSystem = createAsyncThunk(
  'system/updateSystem',
  ({ id, data }: { id: number; data: SystemUpdate }) => systemService.updateSystem(id, data)
);

export const deleteSystem = createAsyncThunk('system/deleteSystem', async (id: number) => {
  await systemService.deleteSystem(id);
  return id;
});

export const fetchSubSystems = createAsyncThunk(
  'system/fetchSubSystems',
  (systemId: number) => systemService.listSubSystems(systemId)
);

export const createSubSystem = createAsyncThunk(
  'system/createSubSystem',
  ({ systemId, data }: { systemId: number; data: SubSystemCreate }) =>
    systemService.createSubSystem(systemId, data)
);

export const updateSubSystem = createAsyncThunk(
  'system/updateSubSystem',
  ({ systemId, subId, data }: { systemId: number; subId: number; data: SubSystemUpdate }) =>
    systemService.updateSubSystem(systemId, subId, data)
);

export const fetchSubSystem = createAsyncThunk(
  'system/fetchSubSystem',
  async ({ systemId, subId }: { systemId: number; subId: number }) => {
    return systemService.getSubSystem(systemId, subId);
  }
);

export const deleteSubSystem = createAsyncThunk(
  'system/deleteSubSystem',
  async ({ systemId, subId }: { systemId: number; subId: number }) => {
    await systemService.deleteSubSystem(systemId, subId);
    return subId;
  }
);

const systemSlice = createSlice({
  name: 'system',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      // fetchSystems
      .addCase(fetchSystems.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchSystems.fulfilled, (state, action) => {
        state.systems = action.payload;
        state.loading = false;
      })
      .addCase(fetchSystems.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch systems';
      })
      // fetchSystem
      .addCase(fetchSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchSystem.fulfilled, (state, action) => {
        state.currentSystem = action.payload;
        state.loading = false;
      })
      .addCase(fetchSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch system';
      })
      // createSystem
      .addCase(createSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(createSystem.fulfilled, (state, action) => {
        state.systems.push(action.payload);
        state.loading = false;
      })
      .addCase(createSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create system';
      })
      // updateSystem
      .addCase(updateSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(updateSystem.fulfilled, (state, action) => {
        const idx = state.systems.findIndex((s) => s.id === action.payload.id);
        if (idx !== -1) state.systems[idx] = action.payload;
        if (state.currentSystem?.id === action.payload.id) state.currentSystem = action.payload;
        state.loading = false;
      })
      .addCase(updateSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to update system';
      })
      // deleteSystem
      .addCase(deleteSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(deleteSystem.fulfilled, (state, action) => {
        state.systems = state.systems.filter((s) => s.id !== action.payload);
        if (state.currentSystem?.id === action.payload) state.currentSystem = null;
        state.loading = false;
      })
      .addCase(deleteSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete system';
      })
      // fetchSubSystem
      .addCase(fetchSubSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchSubSystem.fulfilled, (state, action) => {
        state.currentSubSystem = action.payload;
        state.loading = false;
      })
      .addCase(fetchSubSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch subsystem';
      })
      // fetchSubSystems
      .addCase(fetchSubSystems.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchSubSystems.fulfilled, (state, action) => {
        state.subsystems = action.payload;
        state.loading = false;
      })
      .addCase(fetchSubSystems.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch subsystems';
      })
      // createSubSystem
      .addCase(createSubSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(createSubSystem.fulfilled, (state, action) => {
        state.subsystems.push(action.payload);
        state.loading = false;
      })
      .addCase(createSubSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create subsystem';
      })
      // updateSubSystem
      .addCase(updateSubSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(updateSubSystem.fulfilled, (state, action) => {
        const idx = state.subsystems.findIndex((s) => s.id === action.payload.id);
        if (idx !== -1) state.subsystems[idx] = action.payload;
        state.loading = false;
      })
      .addCase(updateSubSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to update subsystem';
      })
      // deleteSubSystem
      .addCase(deleteSubSystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(deleteSubSystem.fulfilled, (state, action) => {
        state.subsystems = state.subsystems.filter((s) => s.id !== action.payload);
        state.loading = false;
      })
      .addCase(deleteSubSystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete subsystem';
      });
  },
});

export default systemSlice.reducer;
