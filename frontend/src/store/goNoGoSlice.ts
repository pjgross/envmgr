import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { goNoGoService } from '../services/goNoGoService';
import { formatApiError } from '../services/apiError';
import type {
  GoNoGoConditionRead,
  GoNoGoDecisionCreate,
  GoNoGoDecisionRead,
  GoNoGoPerspectiveCreate,
  GoNoGoPerspectiveRead,
  GoNoGoPerspectiveUpdate,
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

const sortPerspectives = (rows: GoNoGoPerspectiveRead[]): GoNoGoPerspectiveRead[] =>
  [...rows].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id);

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

// Admin-only writes on the perspective vocabulary (Task 10's gap over Task
// 7's brief). Both reject with `formatApiError` — a duplicate name is a 409
// whose `detail` IS the message a caller needs to see, and RTK's default
// `miniSerializeError` would otherwise flatten it to "Request failed with
// status code 409".
export const createPerspective = createAsyncThunk<
  GoNoGoPerspectiveRead,
  GoNoGoPerspectiveCreate,
  { rejectValue: string }
>('goNoGo/createPerspective', async (data, { rejectWithValue }) => {
  try {
    return await goNoGoService.createPerspective(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create perspective'));
  }
});

export const updatePerspective = createAsyncThunk<
  GoNoGoPerspectiveRead,
  { id: number; data: GoNoGoPerspectiveUpdate },
  { rejectValue: string }
>('goNoGo/updatePerspective', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await goNoGoService.updatePerspective(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update perspective'));
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
        // useServerGrid aborts a superseded request rather than ignoring its
        // reply, and React StrictMode's double-effect fires this on first
        // mount. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard the tab renders a load failure for a request that was never
        // a failure (see buildSlice.fetchBuilds.rejected / bookingSlice.
        // fetchBookings.rejected, the two existing precedents for this).
        if (action.meta.aborted) return;
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
        // Same abort-vs-failure trap as fetchDecisions.rejected above —
        // fetchPerspectives is dispatched from the record-decision dialog on
        // mount and is exposed to the identical StrictMode double-effect.
        if (action.meta.aborted) return;
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
      })
      // createPerspective / updatePerspective — `perspectives` holds the
      // WHOLE tenant vocabulary (no paging), so an in-place insert/update is
      // safe, unlike `recordDecision` above.
      .addCase(createPerspective.fulfilled, (state, action) => {
        state.perspectives = sortPerspectives([...state.perspectives, action.payload]);
      })
      .addCase(updatePerspective.fulfilled, (state, action) => {
        state.perspectives = sortPerspectives(
          state.perspectives.map((p) => (p.id === action.payload.id ? action.payload : p))
        );
      });
  },
});

export default goNoGoSlice.reducer;
