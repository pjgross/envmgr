import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type {
  ReleaseEventTypeResponse,
  ReleaseEventTypeCreatePayload,
  ReleaseEventTypeUpdatePayload,
} from '../types/releaseEvent';
import { releaseEventTypeService } from '../services/releaseEventTypeService';

interface ReleaseEventTypeState {
  list: ReleaseEventTypeResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: ReleaseEventTypeState = {
  list: [],
  loading: false,
  error: null,
};

export const fetchReleaseEventTypes = createAsyncThunk('releaseEventType/list', () =>
  releaseEventTypeService.list()
);

export const createReleaseEventType = createAsyncThunk(
  'releaseEventType/create',
  (data: ReleaseEventTypeCreatePayload) => releaseEventTypeService.create(data)
);

export const updateReleaseEventType = createAsyncThunk(
  'releaseEventType/update',
  ({ id, data }: { id: number; data: ReleaseEventTypeUpdatePayload }) =>
    releaseEventTypeService.update(id, data)
);

export const deleteReleaseEventType = createAsyncThunk(
  'releaseEventType/delete',
  (id: number) => releaseEventTypeService.remove(id).then(() => id)
);

const releaseEventTypeSlice = createSlice({
  name: 'releaseEventType',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchReleaseEventTypes.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchReleaseEventTypes.fulfilled, (state, action) => { state.loading = false; state.list = action.payload; })
      .addCase(fetchReleaseEventTypes.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load release event types'; })

      .addCase(createReleaseEventType.fulfilled, (state, action) => { state.list.push(action.payload); })

      .addCase(updateReleaseEventType.fulfilled, (state, action) => {
        const idx = state.list.findIndex((et) => et.id === action.payload.id);
        if (idx !== -1) state.list[idx] = action.payload;
      })

      .addCase(deleteReleaseEventType.fulfilled, (state, action) => {
        state.list = state.list.filter((et) => et.id !== action.payload);
      });
  },
});

export default releaseEventTypeSlice.reducer;
