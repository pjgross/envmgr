import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type {
  ChangeRequestResponse,
  ChangeRequestDetailResponse,
  ChangeRequestCreatePayload,
  ChangeRequestUpdatePayload,
  ChangeRequestTransitionPayload,
  ChangeRequestListFilters,
} from '../types/changeRequest';
import { changeRequestService } from '../services/changeRequestService';

interface ChangeRequestState {
  list: ChangeRequestResponse[];
  total: number;
  detail: ChangeRequestDetailResponse | null;
  loading: boolean;
  /**
   * The list query's own flag. `loading` is shared by the other thunks, and
   * an aborted list request on unmount has no successor to clear it —
   * isolating the list keeps that from hanging every other consumer of the
   * slice.
   */
  listLoading: boolean;
  error: string | null;
  filters: ChangeRequestListFilters;
}

const initialState: ChangeRequestState = {
  list: [],
  total: 0,
  detail: null,
  loading: false,
  listLoading: false,
  error: null,
  filters: {},
};

export const fetchChangeRequests = createAsyncThunk(
  'changeRequest/list',
  (filters: ChangeRequestListFilters = {}) => changeRequestService.list(filters)
);

export const fetchChangeRequest = createAsyncThunk('changeRequest/get', (id: number) =>
  changeRequestService.get(id)
);

export const createChangeRequest = createAsyncThunk(
  'changeRequest/create',
  (data: ChangeRequestCreatePayload) => changeRequestService.create(data)
);

export const updateChangeRequest = createAsyncThunk(
  'changeRequest/update',
  ({ id, data }: { id: number; data: ChangeRequestUpdatePayload }) =>
    changeRequestService.update(id, data)
);

export const transitionChangeRequest = createAsyncThunk(
  'changeRequest/transition',
  ({ id, data }: { id: number; data: ChangeRequestTransitionPayload }) =>
    changeRequestService.transition(id, data)
);

export const deleteChangeRequest = createAsyncThunk(
  'changeRequest/delete',
  (id: number) => changeRequestService.remove(id).then(() => id)
);

const changeRequestSlice = createSlice({
  name: 'changeRequest',
  initialState,
  reducers: {
    setFilters(state, action: { payload: ChangeRequestListFilters }) {
      state.filters = action.payload;
    },
    clearDetail(state) {
      state.detail = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchChangeRequests.pending, (state) => {
        state.listLoading = true;
        state.error = null;
      })
      .addCase(fetchChangeRequests.fulfilled, (state, action) => {
        state.list = action.payload.rows;
        state.total = action.payload.total;
        state.listLoading = false;
      })
      .addCase(fetchChangeRequests.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than ignoring its
        // reply. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard the spinner flickers off and `error` is set to 'Aborted'
        // while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to load change requests';
      })

      .addCase(fetchChangeRequest.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchChangeRequest.fulfilled, (state, action) => {
        state.loading = false;
        state.detail = action.payload;
      })
      .addCase(fetchChangeRequest.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load change request';
      })

      .addCase(createChangeRequest.fulfilled, (state, action) => {
        state.list.unshift(action.payload);
      })

      .addCase(updateChangeRequest.fulfilled, (state, action) => {
        const idx = state.list.findIndex((c) => c.id === action.payload.id);
        if (idx !== -1) state.list[idx] = action.payload;
        if (state.detail && state.detail.id === action.payload.id) {
          state.detail = { ...state.detail, ...action.payload };
        }
      })

      .addCase(transitionChangeRequest.fulfilled, (state, action) => {
        const idx = state.list.findIndex((c) => c.id === action.payload.id);
        if (idx !== -1) state.list[idx] = action.payload;
        if (state.detail && state.detail.id === action.payload.id) {
          state.detail = { ...state.detail, ...action.payload };
        }
      })

      .addCase(deleteChangeRequest.fulfilled, (state, action) => {
        state.list = state.list.filter((c) => c.id !== action.payload);
        if (state.detail && state.detail.id === action.payload) state.detail = null;
      });
  },
});

export const { setFilters, clearDetail } = changeRequestSlice.actions;
export default changeRequestSlice.reducer;
