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
  byBuild: Record<number, Deployment[]>;
  current: Deployment | null;
  loading: boolean;
  error: string | null;
}

const initialState: DeploymentState = {
  items: [],
  byBuild: {},
  current: null,
  loading: false,
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
    b.addCase(fetchDeployments.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchDeployments.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchDeployments.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load deployments';
    });
    b.addCase(fetchDeploymentById.fulfilled, (s, a) => { s.current = a.payload; });
    b.addCase(fetchDeploymentsByBuild.fulfilled, (s, a) => {
      s.byBuild[a.meta.arg] = a.payload;
    });
    b.addCase(linkDeploymentChange.fulfilled, (s, a) => {
      s.current = a.payload;
      s.items = s.items.map((d) => (d.id === a.payload.id ? a.payload : d));
    });
  },
});

export default slice.reducer;
