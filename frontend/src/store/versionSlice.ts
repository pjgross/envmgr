import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { versionService } from '../services/versionService';
import type { VersionResponse, VersionCreate, VersionUpdate, ImportResult } from '../types/version';

interface VersionState {
  versions: VersionResponse[];
  loading: boolean;
  error: string | null;
  lastImportResult: ImportResult | null;
  importLoading: boolean;
  importError: string | null;
}

const initialState: VersionState = {
  versions: [],
  loading: false,
  error: null,
  lastImportResult: null,
  importLoading: false,
  importError: null,
};

export const fetchVersions = createAsyncThunk(
  'version/fetchVersions',
  ({ envId, currentOnly }: { envId: number; currentOnly?: boolean }) =>
    versionService.listVersions(envId, currentOnly)
);

export const recordVersion = createAsyncThunk(
  'version/recordVersion',
  ({ envId, data }: { envId: number; data: VersionCreate }) =>
    versionService.recordVersion(envId, data)
);

export const updateVersion = createAsyncThunk(
  'version/updateVersion',
  ({ envId, versionId, data }: { envId: number; versionId: number; data: VersionUpdate }) =>
    versionService.updateVersion(envId, versionId, data)
);

export const deleteVersion = createAsyncThunk(
  'version/deleteVersion',
  async ({ envId, versionId }: { envId: number; versionId: number }) => {
    await versionService.deleteVersion(envId, versionId);
    return versionId;
  }
);

export const importEnvironments = createAsyncThunk(
  'version/importEnvironments',
  (file: File) => versionService.importEnvironments(file)
);

export const importSystems = createAsyncThunk(
  'version/importSystems',
  (file: File) => versionService.importSystems(file)
);

const versionSlice = createSlice({
  name: 'version',
  initialState,
  reducers: {
    clearVersions(state) {
      state.versions = [];
    },
    clearImportResult(state) {
      state.lastImportResult = null;
      state.importError = null;
    },
  },
  extraReducers: (builder) => {
    // fetchVersions
    builder.addCase(fetchVersions.pending, (state) => {
      state.loading = true;
      state.error = null;
    });
    builder.addCase(fetchVersions.fulfilled, (state, action) => {
      state.loading = false;
      state.versions = action.payload;
    });
    builder.addCase(fetchVersions.rejected, (state, action) => {
      state.loading = false;
      state.error = action.error.message ?? 'Failed to fetch versions';
    });

    // recordVersion
    builder.addCase(recordVersion.pending, (state) => {
      state.loading = true;
      state.error = null;
    });
    builder.addCase(recordVersion.fulfilled, (state, action) => {
      state.loading = false;
      state.versions = [...state.versions, action.payload];
    });
    builder.addCase(recordVersion.rejected, (state, action) => {
      state.loading = false;
      state.error = action.error.message ?? 'Failed to record version';
    });

    // updateVersion
    builder.addCase(updateVersion.fulfilled, (state, action) => {
      const idx = state.versions.findIndex((v) => v.id === action.payload.id);
      if (idx !== -1) state.versions[idx] = action.payload;
    });

    // deleteVersion
    builder.addCase(deleteVersion.fulfilled, (state, action) => {
      state.versions = state.versions.filter((v) => v.id !== action.payload);
    });

    // importEnvironments
    builder.addCase(importEnvironments.pending, (state) => {
      state.importLoading = true;
      state.importError = null;
      state.lastImportResult = null;
    });
    builder.addCase(importEnvironments.fulfilled, (state, action) => {
      state.importLoading = false;
      state.lastImportResult = action.payload;
    });
    builder.addCase(importEnvironments.rejected, (state, action) => {
      state.importLoading = false;
      state.importError = action.error.message ?? 'Import failed';
    });

    // importSystems
    builder.addCase(importSystems.pending, (state) => {
      state.importLoading = true;
      state.importError = null;
      state.lastImportResult = null;
    });
    builder.addCase(importSystems.fulfilled, (state, action) => {
      state.importLoading = false;
      state.lastImportResult = action.payload;
    });
    builder.addCase(importSystems.rejected, (state, action) => {
      state.importLoading = false;
      state.importError = action.error.message ?? 'Import failed';
    });
  },
});

export const { clearVersions, clearImportResult } = versionSlice.actions;
export default versionSlice.reducer;
