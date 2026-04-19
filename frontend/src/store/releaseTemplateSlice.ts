import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type {
  ReleaseTemplateResponse,
  ReleaseTemplateCreatePayload,
  ReleaseTemplateUpdatePayload,
  ReleaseTemplateInstantiatePayload,
} from '../types/releaseTemplate';
import type { ReleaseResponse } from '../types/release';
import { releaseTemplateService } from '../services/releaseTemplateService';

interface ReleaseTemplateState {
  list: ReleaseTemplateResponse[];
  detail: ReleaseTemplateResponse | null;
  loading: boolean;
  error: string | null;
}

const initialState: ReleaseTemplateState = {
  list: [],
  detail: null,
  loading: false,
  error: null,
};

export const fetchReleaseTemplates = createAsyncThunk('releaseTemplate/list', () =>
  releaseTemplateService.list()
);

export const fetchReleaseTemplate = createAsyncThunk('releaseTemplate/get', (id: number) =>
  releaseTemplateService.get(id)
);

export const createReleaseTemplate = createAsyncThunk(
  'releaseTemplate/create',
  (data: ReleaseTemplateCreatePayload) => releaseTemplateService.create(data)
);

export const updateReleaseTemplate = createAsyncThunk(
  'releaseTemplate/update',
  ({ id, data }: { id: number; data: ReleaseTemplateUpdatePayload }) =>
    releaseTemplateService.update(id, data)
);

export const deleteReleaseTemplate = createAsyncThunk(
  'releaseTemplate/delete',
  (id: number) => releaseTemplateService.remove(id).then(() => id)
);

export const instantiateReleaseTemplate = createAsyncThunk(
  'releaseTemplate/instantiate',
  ({ id, data }: { id: number; data: ReleaseTemplateInstantiatePayload }): Promise<ReleaseResponse> =>
    releaseTemplateService.instantiate(id, data)
);

const releaseTemplateSlice = createSlice({
  name: 'releaseTemplate',
  initialState,
  reducers: {
    clearDetail(state) {
      state.detail = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchReleaseTemplates.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchReleaseTemplates.fulfilled, (state, action) => { state.loading = false; state.list = action.payload; })
      .addCase(fetchReleaseTemplates.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load release templates'; })

      .addCase(fetchReleaseTemplate.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchReleaseTemplate.fulfilled, (state, action) => { state.loading = false; state.detail = action.payload; })
      .addCase(fetchReleaseTemplate.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load release template'; })

      .addCase(createReleaseTemplate.fulfilled, (state, action) => { state.list.push(action.payload); })

      .addCase(updateReleaseTemplate.fulfilled, (state, action) => {
        const idx = state.list.findIndex((t) => t.id === action.payload.id);
        if (idx !== -1) state.list[idx] = action.payload;
        if (state.detail?.id === action.payload.id) state.detail = action.payload;
      })

      .addCase(deleteReleaseTemplate.fulfilled, (state, action) => {
        state.list = state.list.filter((t) => t.id !== action.payload);
        if (state.detail?.id === action.payload) state.detail = null;
      });
  },
});

export const { clearDetail } = releaseTemplateSlice.actions;
export default releaseTemplateSlice.reducer;
