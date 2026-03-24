import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentService } from '../services/environmentService';
import type {
  EnvironmentResponse,
  EnvironmentSystemsResponse,
  EnvironmentSubsystemResponse,
  EnvironmentCreate,
  EnvironmentUpdate,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
  EnvironmentSubsystemUpdate,
} from '../types/environment';

interface EnvironmentState {
  environments: EnvironmentResponse[];
  currentEnvironment: EnvironmentResponse | null;
  environmentSystemsData: EnvironmentSystemsResponse;
  envSubsystems: EnvironmentSubsystemResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentState = {
  environments: [],
  currentEnvironment: null,
  environmentSystemsData: { systems: [], missing_systems: [] },
  envSubsystems: [],
  loading: false,
  error: null,
};

export const fetchEnvironments = createAsyncThunk('environment/fetchEnvironments', () =>
  environmentService.listEnvironments()
);

export const fetchEnvironment = createAsyncThunk('environment/fetchEnvironment', (id: number) =>
  environmentService.getEnvironment(id)
);

export const createEnvironment = createAsyncThunk(
  'environment/createEnvironment',
  (data: EnvironmentCreate) => environmentService.createEnvironment(data)
);

export const updateEnvironment = createAsyncThunk(
  'environment/updateEnvironment',
  ({ id, data }: { id: number; data: EnvironmentUpdate }) =>
    environmentService.updateEnvironment(id, data)
);

export const deleteEnvironment = createAsyncThunk(
  'environment/deleteEnvironment',
  async (id: number) => {
    await environmentService.deleteEnvironment(id);
    return id;
  }
);

export const fetchEnvironmentSystems = createAsyncThunk(
  'environment/fetchEnvironmentSystems',
  (envId: number) => environmentService.listSystemsInEnvironment(envId)
);

export const addSystemToEnvironment = createAsyncThunk(
  'environment/addSystemToEnvironment',
  ({ envId, data }: { envId: number; data: EnvironmentSystemCreate }) =>
    environmentService.addSystemToEnvironment(envId, data)
);

export const updateSystemInEnvironment = createAsyncThunk(
  'environment/updateSystemInEnvironment',
  ({ envId, systemId, data }: { envId: number; systemId: number; data: EnvironmentSystemUpdate }) =>
    environmentService.updateSystemInEnvironment(envId, systemId, data)
);

export const removeSystemFromEnvironment = createAsyncThunk(
  'environment/removeSystemFromEnvironment',
  async ({ envId, systemId }: { envId: number; systemId: number }) => {
    await environmentService.removeSystemFromEnvironment(envId, systemId);
    return { envId, systemId };
  }
);

export const fetchEnvSubsystems = createAsyncThunk(
  'environment/fetchEnvSubsystems',
  (envId: number) => environmentService.listEnvironmentSubsystems(envId)
);

export const updateEnvSubsystem = createAsyncThunk(
  'environment/updateEnvSubsystem',
  ({ envId, subsystemId, data }: { envId: number; subsystemId: number; data: EnvironmentSubsystemUpdate }) =>
    environmentService.updateEnvironmentSubsystem(envId, subsystemId, data)
);

const environmentSlice = createSlice({
  name: 'environment',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      // fetchEnvironments
      .addCase(fetchEnvironments.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchEnvironments.fulfilled, (state, action) => {
        state.environments = action.payload;
        state.loading = false;
      })
      .addCase(fetchEnvironments.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch environments';
      })
      // fetchEnvironment
      .addCase(fetchEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchEnvironment.fulfilled, (state, action) => {
        state.currentEnvironment = action.payload;
        state.loading = false;
      })
      .addCase(fetchEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch environment';
      })
      // createEnvironment
      .addCase(createEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(createEnvironment.fulfilled, (state, action) => {
        state.environments.push(action.payload);
        state.loading = false;
      })
      .addCase(createEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create environment';
      })
      // updateEnvironment
      .addCase(updateEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(updateEnvironment.fulfilled, (state, action) => {
        const idx = state.environments.findIndex((e) => e.id === action.payload.id);
        if (idx !== -1) state.environments[idx] = action.payload;
        if (state.currentEnvironment?.id === action.payload.id) {
          state.currentEnvironment = action.payload;
        }
        state.loading = false;
      })
      .addCase(updateEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to update environment';
      })
      // deleteEnvironment
      .addCase(deleteEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(deleteEnvironment.fulfilled, (state, action) => {
        state.environments = state.environments.filter((e) => e.id !== action.payload);
        if (state.currentEnvironment?.id === action.payload) state.currentEnvironment = null;
        state.loading = false;
      })
      .addCase(deleteEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete environment';
      })
      // fetchEnvironmentSystems
      .addCase(fetchEnvironmentSystems.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchEnvironmentSystems.fulfilled, (state, action) => {
        state.environmentSystemsData = action.payload;
        state.loading = false;
      })
      .addCase(fetchEnvironmentSystems.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch environment systems';
      })
      // addSystemToEnvironment
      .addCase(addSystemToEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(addSystemToEnvironment.fulfilled, (state, action) => {
        state.environmentSystemsData.systems.push(action.payload);
        state.loading = false;
      })
      .addCase(addSystemToEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to add system to environment';
      })
      // updateSystemInEnvironment
      .addCase(updateSystemInEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(updateSystemInEnvironment.fulfilled, (state, action) => {
        const idx = state.environmentSystemsData.systems.findIndex((s) => s.id === action.payload.id);
        if (idx !== -1) state.environmentSystemsData.systems[idx] = action.payload;
        state.loading = false;
      })
      .addCase(updateSystemInEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to update system in environment';
      })
      // removeSystemFromEnvironment
      .addCase(removeSystemFromEnvironment.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(removeSystemFromEnvironment.fulfilled, (state, action) => {
        state.environmentSystemsData.systems = state.environmentSystemsData.systems.filter(
          (s) => s.system_id !== action.payload.systemId
        );
        state.loading = false;
      })
      .addCase(removeSystemFromEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to remove system from environment';
      })
      // fetchEnvSubsystems
      .addCase(fetchEnvSubsystems.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchEnvSubsystems.fulfilled, (state, action) => {
        state.envSubsystems = action.payload;
        state.loading = false;
      })
      .addCase(fetchEnvSubsystems.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch subsystems';
      })
      // updateEnvSubsystem
      .addCase(updateEnvSubsystem.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(updateEnvSubsystem.fulfilled, (state, action) => {
        const idx = state.envSubsystems.findIndex((s) => s.subsystem_id === action.payload.subsystem_id);
        if (idx !== -1) state.envSubsystems[idx] = action.payload;
        state.loading = false;
      })
      .addCase(updateEnvSubsystem.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to update subsystem';
      });
  },
});

export default environmentSlice.reducer;
