import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { decommissionService } from '../services/decommissionService';
import { formatApiError } from '../services/apiError';
import type {
  Attestation,
  AttestationCreate,
  CancelRequest,
  Decommission,
  DecommissionCreate,
  DecommissionState,
  DecommissionStep,
  DecommissionWorklistRow,
  ExtensionDecision,
  ExtensionRequest,
  RemainingBookingSummary,
  TeardownResult,
} from '../types/decommission';

interface DecommissionSliceState {
  // The live/most-recent decommission for whichever environment's panel is
  // on screen. Cleared on `pending`, same rule fetchProject's/
  // fetchEnvironmentGroup's `current` follow: a stale decommission must not
  // render under a different environment's panel while the new fetch is in
  // flight.
  current: Decommission | null;
  // Bookings teardown DID NOT touch, from the most recent tearDown response.
  // Cleared alongside `current` — a disclosure from one decommission must
  // not linger under a different one.
  remainingBookings: RemainingBookingSummary[];
  loading: boolean;
  error: string | null;

  // The worklist — server-paged, GET /decommissions.
  worklist: DecommissionWorklistRow[];
  worklistTotal: number;
  worklistLoading: boolean;
  worklistError: string | null;

  // The tenant's checklist vocabulary — GET /tenant/decommission-steps. Not
  // paged (see decommissionService.listSteps): a small, tenant-configured
  // list, not a growth-bearing one. Task 12's panel is the first reader.
  steps: DecommissionStep[];
  stepsLoading: boolean;
  stepsError: string | null;
}

const initialState: DecommissionSliceState = {
  current: null,
  remainingBookings: [],
  loading: false,
  error: null,

  worklist: [],
  worklistTotal: 0,
  worklistLoading: false,
  worklistError: null,

  steps: [],
  stepsLoading: false,
  stepsError: null,
};

// Every mutating thunk rejects with `rejectWithValue(formatApiError(...))`
// rather than letting the axios error escape. Redux Toolkit serialises an
// escaping error with miniSerializeError, which copies only
// name/message/stack/code — `response.data.detail`, where the backend puts
// its reason (e.g. "Sign these first: final_backup, teardown"), is dropped,
// and a real AxiosError's `.message` is the generic "Request failed with
// status code 422". Every caller reads `result.payload`, never
// `result.error.message` — see CLAUDE.md's note on BookingTypesPanel /
// ComponentTypesPanel / LifecycleTemplatesPanel, the three earlier
// conversions for exactly this gap.

export const fetchDecommission = createAsyncThunk<
  Decommission | null,
  number,
  { rejectValue: string }
>('decommission/fetch', async (environmentId, { rejectWithValue }) => {
  try {
    return await decommissionService.getForEnvironment(environmentId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the decommission'));
  }
});

export const initiateDecommission = createAsyncThunk<
  Decommission,
  { environmentId: number; data: DecommissionCreate },
  { rejectValue: string }
>('decommission/initiate', async ({ environmentId, data }, { rejectWithValue }) => {
  try {
    return await decommissionService.initiate(environmentId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to initiate decommissioning'));
  }
});

export const requestExtension = createAsyncThunk<
  Decommission,
  { decommissionId: number; data: ExtensionRequest },
  { rejectValue: string }
>('decommission/requestExtension', async ({ decommissionId, data }, { rejectWithValue }) => {
  try {
    return await decommissionService.requestExtension(decommissionId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to request an extension'));
  }
});

export const decideExtension = createAsyncThunk<
  Decommission,
  { decommissionId: number; data: ExtensionDecision },
  { rejectValue: string }
>('decommission/decideExtension', async ({ decommissionId, data }, { rejectWithValue }) => {
  try {
    return await decommissionService.decideExtension(decommissionId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to record the extension decision'));
  }
});

// No slice-state handler — signing a step changes nothing on `current`
// (`Decommission` carries no signed-steps field to update; only teardown's
// missing-required-steps check reads attestations, server-side). The caller
// reads `result.payload` directly, same as `contentionService.decide`.
export const signAttestation = createAsyncThunk<
  Attestation,
  { decommissionId: number; data: AttestationCreate },
  { rejectValue: string }
>('decommission/signAttestation', async ({ decommissionId, data }, { rejectWithValue }) => {
  try {
    return await decommissionService.signAttestation(decommissionId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to sign this step'));
  }
});

// THE ONE ACTING THUNK IN B5's FRONTEND — matches the one acting route in
// its backend. A single decommissionId, not an object: no other data
// travels with a teardown.
export const tearDown = createAsyncThunk<TeardownResult, number, { rejectValue: string }>(
  'decommission/tearDown',
  async (decommissionId, { rejectWithValue }) => {
    try {
      return await decommissionService.tearDown(decommissionId);
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to tear down this environment'));
    }
  }
);

export const cancelDecommission = createAsyncThunk<
  Decommission,
  { decommissionId: number; data: CancelRequest },
  { rejectValue: string }
>('decommission/cancel', async ({ decommissionId, data }, { rejectWithValue }) => {
  try {
    return await decommissionService.cancel(decommissionId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to cancel this decommission'));
  }
});

/**
 * The worklist. `page`/`pageSize` (0-based page, following
 * `useServerGrid`'s `paginationModel`) are converted to `limit`/`offset` here
 * rather than by the caller — this thunk is the one place that conversion
 * happens.
 *
 * `state` is OMITTED for "everything" — never `'all'`. That sentinel belongs
 * to `buildParams` (`hooks/serverGridParams.ts`); a vocabulary that also
 * contains `'all'` would build byte-identical params for two different
 * filter states and the grid would never refetch. A3, A4, B2 and B4 each
 * hit this in turn — see `decommissionService.listWorklist`'s own comment.
 */
export const fetchDecommissionWorklist = createAsyncThunk<
  { rows: DecommissionWorklistRow[]; total: number },
  {
    page: number;
    pageSize: number;
    state?: DecommissionState;
    sortBy?: 'scheduled_teardown_at' | 'warned_at' | 'environment';
    sortDir?: 'asc' | 'desc';
  },
  { rejectValue: string }
>(
  'decommission/fetchWorklist',
  async ({ page, pageSize, state, sortBy, sortDir }, { rejectWithValue }) => {
    try {
      return await decommissionService.listWorklist({
        state,
        limit: pageSize,
        offset: page * pageSize,
        sort_by: sortBy,
        sort_dir: sortDir,
      });
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to load the decommission worklist'));
    }
  }
);

// The tenant's checklist vocabulary, for the environment detail panel (Task
// 12) — `active_only=true`, the same default the checklist itself should
// render: a retired step stops gating immediately, so an inactive step has
// no business appearing as something still to sign.
export const fetchDecommissionSteps = createAsyncThunk<
  DecommissionStep[],
  void,
  { rejectValue: string }
>('decommission/fetchSteps', async (_, { rejectWithValue }) => {
  try {
    return await decommissionService.listSteps(true);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the decommission checklist'));
  }
});

const decommissionSlice = createSlice({
  name: 'decommission',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchDecommission.pending, (state) => {
        state.loading = true;
        state.current = null;
        state.remainingBookings = [];
        state.error = null;
      })
      .addCase(fetchDecommission.fulfilled, (state, action) => {
        state.loading = false;
        state.current = action.payload;
      })
      .addCase(fetchDecommission.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load the decommission';
      })
      .addCase(initiateDecommission.fulfilled, (state, action) => {
        state.current = action.payload;
        state.error = null;
      })
      // requestExtension / decideExtension / cancelDecommission each update
      // `current` IN PLACE, only when it's the same decommission — the same
      // guard `updateEnvironment.fulfilled` uses for `currentEnvironment`.
      // These are single-entity mutations, not a paged list, so there is no
      // desync-from-splicing hazard the "pages refetch instead" rule guards
      // against elsewhere in this codebase.
      .addCase(requestExtension.fulfilled, (state, action) => {
        if (state.current?.id === action.payload.id) state.current = action.payload;
      })
      .addCase(decideExtension.fulfilled, (state, action) => {
        if (state.current?.id === action.payload.id) state.current = action.payload;
      })
      .addCase(tearDown.fulfilled, (state, action) => {
        if (state.current?.id === action.payload.id) {
          state.current = action.payload;
          state.remainingBookings = action.payload.remaining_bookings;
        }
      })
      .addCase(cancelDecommission.fulfilled, (state, action) => {
        if (state.current?.id === action.payload.id) state.current = action.payload;
      })
      .addCase(fetchDecommissionWorklist.pending, (state) => {
        state.worklistLoading = true;
        state.worklistError = null;
      })
      .addCase(fetchDecommissionWorklist.fulfilled, (state, action) => {
        state.worklistLoading = false;
        state.worklist = action.payload.rows;
        // The server total, never rows.length — a page's length is not the
        // filtered set (docs/pagination.md).
        state.worklistTotal = action.payload.total;
      })
      .addCase(fetchDecommissionWorklist.rejected, (state, action) => {
        // Task 13's page drives this thunk through `useServerGrid`, which
        // aborts a superseded dispatch rather than merely ignoring its
        // reply. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard, `worklistLoading` would flip back to `false` (the grid's
        // spinner flickers off) and `worklistError` would be set to the
        // fallback message while the real request is still in flight. Same
        // guard `fetchReleases.rejected` carries for the identical reason.
        if (action.meta.aborted) return;
        state.worklistLoading = false;
        state.worklistError = action.payload ?? 'Failed to load the decommission worklist';
      })
      .addCase(fetchDecommissionSteps.pending, (state) => {
        state.stepsLoading = true;
        state.stepsError = null;
      })
      .addCase(fetchDecommissionSteps.fulfilled, (state, action) => {
        state.stepsLoading = false;
        state.steps = action.payload;
      })
      .addCase(fetchDecommissionSteps.rejected, (state, action) => {
        state.stepsLoading = false;
        state.stepsError = action.payload ?? 'Failed to load the decommission checklist';
      });
  },
});

export default decommissionSlice.reducer;
