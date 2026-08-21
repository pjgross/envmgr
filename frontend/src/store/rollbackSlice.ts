import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';

import { rollbackService } from '../services/rollbackService';
import { formatApiError } from '../services/apiError';
import type {
  RollbackPlanResponse,
  RollbackPlanCreate,
  RehearsalResponse,
  RehearsalCreate,
  RollbackAuthorisationResponse,
  RollbackAuthorisationCreate,
  RollbackPolicy,
  RollbackPolicyUpdate,
} from '../types/rollback';

interface RollbackState {
  plans: RollbackPlanResponse[];
  plansLoading: boolean;
  plansError: string | null;

  authorisations: RollbackAuthorisationResponse[];
  authorisationsLoading: boolean;
  authorisationsError: string | null;

  rehearsals: RehearsalResponse[];
  rehearsalsLoading: boolean;
  rehearsalsError: string | null;

  policy: RollbackPolicy | null;
  policyLoading: boolean;
  policyError: string | null;
}

const initialState: RollbackState = {
  plans: [],
  plansLoading: false,
  plansError: null,

  authorisations: [],
  authorisationsLoading: false,
  authorisationsError: null,

  rehearsals: [],
  rehearsalsLoading: false,
  rehearsalsError: null,

  policy: null,
  policyLoading: false,
  policyError: null,
};

// --- Rollback plans ---

export const fetchRollbackPlans = createAsyncThunk<
  RollbackPlanResponse[],
  number,
  { rejectValue: string }
>('rollback/fetchPlans', async (releaseId, { rejectWithValue }) => {
  try {
    return await rollbackService.listPlans(releaseId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load rollback plans'));
  }
});

export const upsertRollbackPlan = createAsyncThunk<
  RollbackPlanResponse,
  { releaseId: number; data: RollbackPlanCreate },
  { rejectValue: string }
>('rollback/upsertPlan', async ({ releaseId, data }, { rejectWithValue }) => {
  try {
    return await rollbackService.upsertPlan(releaseId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to save the rollback plan'));
  }
});

export const agreeRollbackPlan = createAsyncThunk<
  RollbackPlanResponse,
  { releaseId: number; planId: number },
  { rejectValue: string }
>('rollback/agreePlan', async ({ releaseId, planId }, { rejectWithValue }) => {
  try {
    return await rollbackService.agreePlan(releaseId, planId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to record agreement'));
  }
});

export const deleteRollbackPlan = createAsyncThunk<
  number,
  { releaseId: number; planId: number },
  { rejectValue: string }
>('rollback/deletePlan', async ({ releaseId, planId }, { rejectWithValue }) => {
  try {
    await rollbackService.deletePlan(releaseId, planId);
    return planId;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to delete the rollback plan'));
  }
});

// --- Rollback authorisations ---

export const fetchRollbackAuthorisations = createAsyncThunk<
  RollbackAuthorisationResponse[],
  number,
  { rejectValue: string }
>('rollback/fetchAuthorisations', async (releaseId, { rejectWithValue }) => {
  try {
    return await rollbackService.listAuthorisations(releaseId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load rollback authorisations'));
  }
});

export const recordRollbackAuthorisation = createAsyncThunk<
  RollbackAuthorisationResponse,
  { releaseId: number; data: RollbackAuthorisationCreate },
  { rejectValue: string }
>('rollback/recordAuthorisation', async ({ releaseId, data }, { rejectWithValue }) => {
  try {
    return await rollbackService.recordAuthorisation(releaseId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to record the rollback'));
  }
});

// --- Rehearsals ---

export const fetchRehearsals = createAsyncThunk<
  RehearsalResponse[],
  number,
  { rejectValue: string }
>('rollback/fetchRehearsals', async (systemId, { rejectWithValue }) => {
  try {
    return await rollbackService.listRehearsals(systemId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load rollback rehearsals'));
  }
});

export const recordRehearsal = createAsyncThunk<
  RehearsalResponse,
  { systemId: number; data: RehearsalCreate },
  { rejectValue: string }
>('rollback/recordRehearsal', async ({ systemId, data }, { rejectWithValue }) => {
  try {
    return await rollbackService.recordRehearsal(systemId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to record the rehearsal'));
  }
});

// --- Policy ---

export const fetchRollbackPolicy = createAsyncThunk<
  RollbackPolicy,
  void,
  { rejectValue: string }
>('rollback/fetchPolicy', async (_, { rejectWithValue }) => {
  try {
    return await rollbackService.getPolicy();
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the rollback policy'));
  }
});

export const updateRollbackPolicy = createAsyncThunk<
  RollbackPolicy,
  RollbackPolicyUpdate,
  { rejectValue: string }
>('rollback/updatePolicy', async (data, { rejectWithValue }) => {
  try {
    return await rollbackService.updatePolicy(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to save the rollback policy'));
  }
});

const rollbackSlice = createSlice({
  name: 'rollback',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      // Plans
      .addCase(fetchRollbackPlans.pending, (state) => {
        state.plansLoading = true;
        state.plansError = null;
        // Cleared on pending, not just fulfilled — a panel that refetches on
        // a releaseId change must not go on rendering the previous
        // release's plans under the new heading while the fetch is in
        // flight (same rule fetchLifecyclePolicy follows).
        state.plans = [];
      })
      .addCase(fetchRollbackPlans.fulfilled, (state, action) => {
        state.plansLoading = false;
        state.plans = action.payload;
      })
      .addCase(fetchRollbackPlans.rejected, (state, action) => {
        state.plansLoading = false;
        state.plansError = action.payload ?? 'Failed to load rollback plans';
      })
      .addCase(upsertRollbackPlan.fulfilled, (state, action) => {
        const idx = state.plans.findIndex((p) => p.id === action.payload.id);
        if (idx >= 0) {
          state.plans[idx] = action.payload;
        } else {
          state.plans.push(action.payload);
        }
      })
      .addCase(agreeRollbackPlan.fulfilled, (state, action) => {
        const idx = state.plans.findIndex((p) => p.id === action.payload.id);
        if (idx >= 0) state.plans[idx] = action.payload;
      })
      // Finding 4: agreeRollbackPlan used to have no .rejected handling
      // anywhere — no reducer here, and RollbackPanel.handleAgree never
      // inspected the dispatch result either, so a refused agreement (404 on
      // a plan deleted in another tab, 403, network failure) produced
      // nothing: no alert, no state change, the Agree button just stayed
      // there. Deliberately NOT adding an extraReducers case here — matching
      // deleteRollbackPlan and upsertRollbackPlan immediately below/above,
      // which have none either. `agreeRollbackPlan.rejected` still exists as
      // an action (every createAsyncThunk produces one); the fix is entirely
      // in the caller, which now awaits the dispatch and reads
      // result.payload — see RollbackPanel.handleAgree. Setting `plansError`
      // here as well would duplicate that same message in the ALREADY
      // existing `{plansError && <Alert>}` block used for list-fetch
      // failures, showing the same text in two banners at once.
      .addCase(deleteRollbackPlan.fulfilled, (state, action) => {
        state.plans = state.plans.filter((p) => p.id !== action.payload);
      })

      // Authorisations
      .addCase(fetchRollbackAuthorisations.pending, (state) => {
        state.authorisationsLoading = true;
        state.authorisationsError = null;
        state.authorisations = [];
      })
      .addCase(fetchRollbackAuthorisations.fulfilled, (state, action) => {
        state.authorisationsLoading = false;
        state.authorisations = action.payload;
      })
      .addCase(fetchRollbackAuthorisations.rejected, (state, action) => {
        state.authorisationsLoading = false;
        state.authorisationsError =
          action.payload ?? 'Failed to load rollback authorisations';
      })
      .addCase(recordRollbackAuthorisation.fulfilled, (state, action) => {
        // Newest first, matching the backend's own ordering.
        state.authorisations = [action.payload, ...state.authorisations];
      })

      // Rehearsals
      .addCase(fetchRehearsals.pending, (state) => {
        state.rehearsalsLoading = true;
        state.rehearsalsError = null;
        state.rehearsals = [];
      })
      .addCase(fetchRehearsals.fulfilled, (state, action) => {
        state.rehearsalsLoading = false;
        state.rehearsals = action.payload;
      })
      .addCase(fetchRehearsals.rejected, (state, action) => {
        state.rehearsalsLoading = false;
        state.rehearsalsError = action.payload ?? 'Failed to load rollback rehearsals';
      })
      .addCase(recordRehearsal.fulfilled, (state, action) => {
        // Newest first, matching the backend's own ordering
        // (rehearsed_at desc, id desc).
        state.rehearsals = [action.payload, ...state.rehearsals];
      })

      // Policy
      .addCase(fetchRollbackPolicy.pending, (state) => {
        state.policyLoading = true;
        state.policyError = null;
        state.policy = null;
      })
      .addCase(fetchRollbackPolicy.fulfilled, (state, action) => {
        state.policyLoading = false;
        state.policy = action.payload;
      })
      .addCase(fetchRollbackPolicy.rejected, (state, action) => {
        state.policyLoading = false;
        state.policyError = action.payload ?? 'Failed to load the rollback policy';
      })
      .addCase(updateRollbackPolicy.fulfilled, (state, action) => {
        state.policy = action.payload;
        state.policyError = null;
      })
      .addCase(updateRollbackPolicy.rejected, (state, action) => {
        state.policyError = action.payload ?? 'Failed to save the rollback policy';
      });
  },
});

export default rollbackSlice.reducer;
