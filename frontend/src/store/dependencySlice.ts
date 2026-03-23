import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { dependencyService } from '../services/dependencyService';
import type {
  SystemDependencyResponse,
  SystemDependencyCreate,
  ComponentDependencyResponse,
  ComponentDependencyCreate,
  VerifyResponse,
} from '../types/dependency';

interface DependencyState {
  systemDependencies: SystemDependencyResponse[];
  componentDependencies: ComponentDependencyResponse[];
  verifyResult: VerifyResponse | null;
  loading: boolean;
  error: string | null;
}

const initialState: DependencyState = {
  systemDependencies: [],
  componentDependencies: [],
  verifyResult: null,
  loading: false,
  error: null,
};

// ---------------------------------------------------------------------------
// SystemDependency thunks
// ---------------------------------------------------------------------------

export const fetchSystemDependencies = createAsyncThunk(
  'dependency/fetchSystemDependencies',
  (systemId: number) => dependencyService.listSystemDependencies(systemId)
);

export const createSystemDependency = createAsyncThunk(
  'dependency/createSystemDependency',
  ({ systemId, data }: { systemId: number; data: SystemDependencyCreate }) =>
    dependencyService.createSystemDependency(systemId, data)
);

export const deleteSystemDependency = createAsyncThunk(
  'dependency/deleteSystemDependency',
  async ({ systemId, depId }: { systemId: number; depId: number }) => {
    await dependencyService.deleteSystemDependency(systemId, depId);
    return depId;
  }
);

// ---------------------------------------------------------------------------
// ComponentDependency thunks
// ---------------------------------------------------------------------------

export const fetchComponentDependencies = createAsyncThunk(
  'dependency/fetchComponentDependencies',
  (subsystemId: number) => dependencyService.listComponentDependencies(subsystemId)
);

export const createComponentDependency = createAsyncThunk(
  'dependency/createComponentDependency',
  ({ subsystemId, data }: { subsystemId: number; data: ComponentDependencyCreate }) =>
    dependencyService.createComponentDependency(subsystemId, data)
);

export const deleteComponentDependency = createAsyncThunk(
  'dependency/deleteComponentDependency',
  async ({ subsystemId, depId }: { subsystemId: number; depId: number }) => {
    await dependencyService.deleteComponentDependency(subsystemId, depId);
    return depId;
  }
);

// ---------------------------------------------------------------------------
// Verify thunk
// ---------------------------------------------------------------------------

export const verifyEnvironment = createAsyncThunk(
  'dependency/verifyEnvironment',
  (envId: number) => dependencyService.verifyEnvironment(envId)
);

// ---------------------------------------------------------------------------
// Slice
// ---------------------------------------------------------------------------

const dependencySlice = createSlice({
  name: 'dependency',
  initialState,
  reducers: {
    clearVerifyResult(state) {
      state.verifyResult = null;
    },
  },
  extraReducers: (builder) => {
    // fetchSystemDependencies
    builder
      .addCase(fetchSystemDependencies.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchSystemDependencies.fulfilled, (state, action) => {
        state.loading = false;
        state.systemDependencies = action.payload;
      })
      .addCase(fetchSystemDependencies.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load system dependencies';
      });

    // createSystemDependency
    builder
      .addCase(createSystemDependency.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(createSystemDependency.fulfilled, (state, action) => {
        state.loading = false;
        state.systemDependencies.push(action.payload);
      })
      .addCase(createSystemDependency.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create dependency';
      });

    // deleteSystemDependency
    builder
      .addCase(deleteSystemDependency.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(deleteSystemDependency.fulfilled, (state, action) => {
        state.loading = false;
        state.systemDependencies = state.systemDependencies.filter(
          (d) => d.id !== action.payload
        );
      })
      .addCase(deleteSystemDependency.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete dependency';
      });

    // fetchComponentDependencies
    builder
      .addCase(fetchComponentDependencies.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchComponentDependencies.fulfilled, (state, action) => {
        state.loading = false;
        state.componentDependencies = action.payload;
      })
      .addCase(fetchComponentDependencies.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load component dependencies';
      });

    // createComponentDependency
    builder
      .addCase(createComponentDependency.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(createComponentDependency.fulfilled, (state, action) => {
        state.loading = false;
        state.componentDependencies.push(action.payload);
      })
      .addCase(createComponentDependency.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create component dependency';
      });

    // deleteComponentDependency
    builder
      .addCase(deleteComponentDependency.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(deleteComponentDependency.fulfilled, (state, action) => {
        state.loading = false;
        state.componentDependencies = state.componentDependencies.filter(
          (d) => d.id !== action.payload
        );
      })
      .addCase(deleteComponentDependency.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete component dependency';
      });

    // verifyEnvironment
    builder
      .addCase(verifyEnvironment.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(verifyEnvironment.fulfilled, (state, action) => {
        state.loading = false;
        state.verifyResult = action.payload;
      })
      .addCase(verifyEnvironment.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to verify environment';
      });
  },
});

export const { clearVerifyResult } = dependencySlice.actions;
export default dependencySlice.reducer;
