import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { infrastructureComponentService } from '../services/infrastructureComponentService';
import type {
  HostAttachment,
  InfrastructureComponentCreate,
  InfrastructureComponentResponse,
  InfrastructureComponentSource,
  InfrastructureComponentType,
  InfrastructureComponentUpdate,
} from '../types/infrastructureComponent';

interface InfrastructureComponentState {
  components: InfrastructureComponentResponse[];
  total: number;
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

const initialState: InfrastructureComponentState = {
  components: [],
  total: 0,
  loading: false,
  listLoading: false,
  error: null,
};

export const fetchInfrastructureComponents = createAsyncThunk(
  'infrastructureComponent/fetchAll',
  (params?: {
    component_type?: InfrastructureComponentType;
    provider?: string;
    region?: string;
    source?: InfrastructureComponentSource;
    search?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }) => infrastructureComponentService.listComponents(params)
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
        state.listLoading = true;
        state.error = null;
      })
      .addCase(fetchInfrastructureComponents.fulfilled, (state, action) => {
        state.components = action.payload.rows;
        state.total = action.payload.total;
        state.listLoading = false;
      })
      .addCase(fetchInfrastructureComponents.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than ignoring its
        // reply. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard the spinner flickers off and `error` is set to 'Aborted'
        // while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
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
