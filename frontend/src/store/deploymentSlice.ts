// frontend/src/store/deploymentSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { deploymentService } from '../services/deploymentService';
import type {
  Deployment,
  DeploymentFilters,
  DeploymentLinkChangeRequest,
} from '../types/deployment';

interface DeploymentState {
  items: Deployment[];
  total: number;
  byBuild: Record<number, Deployment[]>;
  current: Deployment | null;
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

const initialState: DeploymentState = {
  items: [],
  total: 0,
  byBuild: {},
  current: null,
  loading: false,
  listLoading: false,
  error: null,
};

export const fetchDeployments = createAsyncThunk(
  'deployment/fetch',
  (filters?: DeploymentFilters) => deploymentService.list(filters),
);
export const fetchDeploymentById = createAsyncThunk(
  'deployment/fetchById',
  (id: number) => deploymentService.get(id),
);
export const fetchDeploymentsByBuild = createAsyncThunk(
  'deployment/fetchByBuild',
  (buildId: number) => deploymentService.list({ build_id: buildId }),
);
export const linkDeploymentChange = createAsyncThunk(
  'deployment/linkChange',
  (args: { id: number; data: DeploymentLinkChangeRequest }) =>
    deploymentService.linkChange(args.id, args.data),
);

const slice = createSlice({
  name: 'deployment',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchDeployments.pending, (s) => { s.listLoading = true; s.error = null; });
    b.addCase(fetchDeployments.fulfilled, (s, a) => {
      s.listLoading = false;
      s.items = a.payload.rows;
      s.total = a.payload.total;
    });
    b.addCase(fetchDeployments.rejected, (s, a) => {
      // useServerGrid aborts a superseded request rather than ignoring its
      // reply. RTK dispatches `pending` for the new request synchronously,
      // then `rejected` for the aborted one on a microtask — without this
      // guard the spinner flickers off and `error` is set to 'Aborted'
      // while the real request is still in flight.
      if (a.meta.aborted) return;
      s.listLoading = false;
      s.error = a.error.message ?? 'Failed to load deployments';
    });
    b.addCase(fetchDeploymentById.fulfilled, (s, a) => { s.current = a.payload; });
    b.addCase(fetchDeploymentsByBuild.fulfilled, (s, a) => {
      s.byBuild[a.meta.arg] = a.payload.rows;
    });
    b.addCase(linkDeploymentChange.fulfilled, (s, a) => {
      s.current = a.payload;
      s.items = s.items.map((d) => (d.id === a.payload.id ? a.payload : d));
    });
  },
});

export default slice.reducer;
