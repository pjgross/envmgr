import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { goNoGoService } from '../services/goNoGoService';
import { formatApiError } from '../services/apiError';
import type {
  GoNoGoConditionRead,
  GoNoGoDecisionCreate,
  GoNoGoDecisionRead,
  GoNoGoPerspectiveRead,
} from '../types/goNoGo';

interface GoNoGoState {
  decisions: GoNoGoDecisionRead[];
  total: number;
  perspectives: GoNoGoPerspectiveRead[];
  loading: boolean;
  error: string | null;
}

const initialState: GoNoGoState = {
  decisions: [],
  total: 0,
  perspectives: [],
  loading: false,
  error: null,
};

// Read-only: no rejectWithValue needed, same shape as fetchComponentTypes.
export const fetchDecisions = createAsyncThunk(
  'goNoGo/fetchDecisions',
  (args: {
    releaseId: number;
    params?: {
      limit?: number;
      offset?: number;
      sort_by?: 'decided_at' | 'outcome';
      sort_dir?: 'asc' | 'desc';
    };
  }) => goNoGoService.list(args.releaseId, args.params ?? {})
);

export const fetchPerspectives = createAsyncThunk(
  'goNoGo/fetchPerspectives',
  (includeInactive: boolean = true) => goNoGoService.listPerspectives(includeInactive)
);

// Mutating thunks reject with `rejectWithValue(formatApiError(...))` rather
// than letting the axios error escape — RTK's default `miniSerializeError`
// drops `response.data.detail`, and a real AxiosError's `.message` is the
// generic "Request failed with status code 422". Consumers must read
// `result.payload`, not `result.error.message`.
export const recordDecision = createAsyncThunk<
  GoNoGoDecisionRead,
  { releaseId: number; data: GoNoGoDecisionCreate },
  { rejectValue: string }
>('goNoGo/record', async ({ releaseId, data }, { rejectWithValue }) => {
  try {
    return await goNoGoService.record(releaseId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to record decision'));
  }
});

export const closeCondition = createAsyncThunk<
  GoNoGoConditionRead,
  { conditionId: number; met: boolean },
  { rejectValue: string }
>('goNoGo/closeCondition', async ({ conditionId, met }, { rejectWithValue }) => {
  try {
    return await goNoGoService.closeCondition(conditionId, met);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update condition'));
  }
});

const goNoGoSlice = createSlice({
  name: 'goNoGo',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      // fetchDecisions
      .addCase(fetchDecisions.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchDecisions.fulfilled, (state, action) => {
        state.loading = false;
        state.decisions = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchDecisions.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch go/no-go decisions';
      })
      // fetchPerspectives
      .addCase(fetchPerspectives.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchPerspectives.fulfilled, (state, action) => {
        state.loading = false;
        state.perspectives = action.payload;
      })
      .addCase(fetchPerspectives.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch go/no-go perspectives';
      })
      // recordDecision — deliberately NO optimistic insert into `decisions`.
      // That array is a server PAGE (newest-first by default, but callers
      // may sort by outcome or hold a later offset), and a freshly recorded
      // decision need not belong on it — the pagination programme's own
      // lesson (docs/pagination.md: "optimistic list surgery is wrong once
      // a slice holds a page"). The caller re-dispatches fetchDecisions.
      .addCase(recordDecision.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(recordDecision.fulfilled, (state) => {
        state.loading = false;
      })
      .addCase(recordDecision.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to record decision';
      })
      // closeCondition — updating a condition IN PLACE on an already-loaded
      // decision is safe (unlike recordDecision above): it neither adds nor
      // removes a row from the page and neither sort key (`decided_at`,
      // `outcome`) depends on condition state, so the row's position on the
      // page cannot change underneath this edit.
      .addCase(closeCondition.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(closeCondition.fulfilled, (state, action) => {
        state.loading = false;
        const decision = state.decisions.find((d) => d.id === action.payload.decision_id);
        if (decision) {
          const idx = decision.conditions.findIndex((c) => c.id === action.payload.id);
          if (idx !== -1) decision.conditions[idx] = action.payload;
        }
      })
      .addCase(closeCondition.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to update condition';
      });
  },
});

export default goNoGoSlice.reducer;
