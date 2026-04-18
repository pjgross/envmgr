import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { infrastructureComponentService } from '../services/infrastructureComponentService';
import type {
  HostAttachment,
  InfrastructureComponentCreate,
  InfrastructureComponentResponse,
  InfrastructureComponentUpdate,
} from '../types/infrastructureComponent';

interface InfrastructureComponentState {
  components: InfrastructureComponentResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: InfrastructureComponentState = {
  components: [],
  loading: false,
  error: null,
};

export const fetchInfrastructureComponents = createAsyncThunk(
  'infrastructureComponent/fetchAll',
  () => infrastructureComponentService.listComponents()
);

export const createInfrastructureComponent = createAsyncThunk(
  'infrastructureComponent/create',
  (data: InfrastructureComponentCreate) =>
    infrastructureComponentService.createComponent(data)
);

export const updateInfrastructureComponent = createAsyncThunk(
  'infrastructureComponent/update',
  ({ id, data }: { id: number; data: InfrastructureComponentUpdate }) =>
    infrastructureComponentService.updateComponent(id, data)
);

export const deleteInfrastructureComponent = createAsyncThunk(
  'infrastructureComponent/delete',
  async (id: number) => {
    await infrastructureComponentService.deleteComponent(id);
    return id;
  }
);

export const setEnvSubsystemHosts = createAsyncThunk(
  'infrastructureComponent/setEnvSubsystemHosts',
  ({
    envId,
    subsystemId,
    attachments,
  }: {
    envId: number;
    subsystemId: number;
    attachments: HostAttachment[];
  }) =>
    infrastructureComponentService.setEnvSubsystemHosts(envId, subsystemId, attachments)
);

const slice = createSlice({
  name: 'infrastructureComponent',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchInfrastructureComponents.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchInfrastructureComponents.fulfilled, (state, action) => {
        state.components = action.payload;
        state.loading = false;
      })
      .addCase(fetchInfrastructureComponents.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch hosts';
      })
      .addCase(createInfrastructureComponent.fulfilled, (state, action) => {
        state.components.push(action.payload);
      })
      .addCase(updateInfrastructureComponent.fulfilled, (state, action) => {
        const idx = state.components.findIndex((c) => c.id === action.payload.id);
        if (idx !== -1) state.components[idx] = action.payload;
      })
      .addCase(deleteInfrastructureComponent.fulfilled, (state, action) => {
        state.components = state.components.filter((c) => c.id !== action.payload);
      });
  },
});

export default slice.reducer;
