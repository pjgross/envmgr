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

      // No createChangeRequest.fulfilled case: `state.list` is now a single
      // server-paged/filtered/sorted window, not "every change request", so
      // there is no correct in-place insertion for a newly created row (it
      // may not belong on the current page at all, and `state.total` would
      // go stale either way). ChangeRequestList is where creation is
      // triggered from (ChangeRequestForm is mounted as its dialog child),
      // and it re-issues its current query via `grid.refetch()` from an
      // `onCreated` callback instead — see ChangeRequestForm's `onCreated`
      // prop.

      .addCase(updateChangeRequest.fulfilled, (state, action) => {
        // No `state.list` write here (previously an in-place splice by id):
        // update/transition/delete are only ever dispatched from
        // ChangeRequestDetail, a separate route from ChangeRequestList, so
        // the list is unmounted when this fires. Splicing a stale row into a
        // page it may no longer belong on (a changed status/sort field) or
        // patching a row that isn't even loaded on the current page is dead
        // weight at best — ChangeRequestList re-fetches its own page fresh
        // every time it mounts, which is the only place this state is read.
        if (state.detail && state.detail.id === action.payload.id) {
          state.detail = { ...state.detail, ...action.payload };
        }
      })

      .addCase(transitionChangeRequest.fulfilled, (state, action) => {
        // Same reasoning as updateChangeRequest.fulfilled above.
        if (state.detail && state.detail.id === action.payload.id) {
          state.detail = { ...state.detail, ...action.payload };
        }
      })

      .addCase(deleteChangeRequest.fulfilled, (state, action) => {
        // Same reasoning as updateChangeRequest.fulfilled above — no
        // `state.list` filter here.
        if (state.detail && state.detail.id === action.payload) state.detail = null;
      });
  },
});

export const { setFilters, clearDetail } = changeRequestSlice.actions;
export default changeRequestSlice.reducer;
