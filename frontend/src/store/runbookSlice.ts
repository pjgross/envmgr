import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { runbookService } from '../services/runbookService';
import { formatApiError } from '../services/apiError';
import type {
  RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead, RunbookTaskCreate,
  RunbookTaskEventRead, RunbookTaskUpdate, TransitionRequest,
} from '../types/runbook';

interface RunbookState {
  plansByRelease: Record<number, RunbookPlanRead[]>;
  byPlan: Record<number, RunbookRead>;
  /** When each plan's composite was last read successfully (ISO). The tab
   * shows it, so a page whose refreshes are failing never looks live. */
  loadedAt: Record<number, string>;
  loading: boolean;
  /** Loading the release's LIST of runbooks failed, keyed by release. */
  listError: Record<number, string>;
  /** The latest re-read of a plan's composite failed, keyed by plan; cleared
   * by the next successful read. Distinct from listError on purpose: a failed
   * refresh leaves the last good composite on screen, and says so. */
  refreshError: Record<number, string>;
}
const initialState: RunbookState = {
  plansByRelease: {}, byPlan: {}, loadedAt: {}, loading: false, listError: {}, refreshError: {},
};
type Rejected = { rejectValue: string };

export const fetchRunbooks = createAsyncThunk<RunbookPlanRead[], number, Rejected>(
  'runbook/list', async (releaseId, { rejectWithValue }) => {
    try { return await runbookService.listForRelease(releaseId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load runbooks')); }
  });

export const fetchRunbook = createAsyncThunk<RunbookRead, number, Rejected>(
  'runbook/get', async (planId, { rejectWithValue }) => {
    try { return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load runbook')); }
  });

// Every write resolves to the composite the server computed — the tab never
// renders a local guess. Consumers read `result.payload` on rejection.
//
// A REFUSED write re-reads the composite before rejecting. A refusal (409,
// 403, 422) usually means the screen was out of date — somebody else moved a
// task — so keeping the old composite would leave a stale Start button and a
// stale "After" column on screen until the next poll, inviting the same
// refused click again.
export const createRunbook = createAsyncThunk<RunbookRead, { releaseId: number; body: RunbookPlanCreate }, Rejected>(
  'runbook/create', async ({ releaseId, body }, { rejectWithValue }) => {
    try { return await runbookService.create(releaseId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to create runbook')); }
  });

export const updateRunbook = createAsyncThunk<RunbookRead, { planId: number; body: RunbookPlanUpdate }, Rejected>(
  'runbook/update', async ({ planId, body }, { dispatch, rejectWithValue }) => {
    try { return await runbookService.update(planId, body); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to update runbook'));
    }
  });

export const deleteRunbook = createAsyncThunk<{ releaseId: number; planId: number }, { releaseId: number; planId: number }, Rejected>(
  'runbook/delete', async (arg, { dispatch, rejectWithValue }) => {
    try { await runbookService.remove(arg.planId); return arg; }
    catch (err) {
      void dispatch(fetchRunbook(arg.planId));
      return rejectWithValue(formatApiError(err, 'Failed to delete runbook'));
    }
  });

export const createTask = createAsyncThunk<RunbookRead, { planId: number; body: RunbookTaskCreate }, Rejected>(
  'runbook/createTask', async ({ planId, body }, { dispatch, rejectWithValue }) => {
    try { await runbookService.createTask(planId, body); return await runbookService.get(planId); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to add task'));
    }
  });

export const updateTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: RunbookTaskUpdate }, Rejected>(
  'runbook/updateTask', async ({ planId, taskId, body }, { dispatch, rejectWithValue }) => {
    try { return await runbookService.updateTask(taskId, body); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to update task'));
    }
  });

export const deleteTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number }, Rejected>(
  'runbook/deleteTask', async ({ planId, taskId }, { dispatch, rejectWithValue }) => {
    try { await runbookService.removeTask(taskId); return await runbookService.get(planId); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to delete task'));
    }
  });

export const setPredecessors = createAsyncThunk<RunbookRead, { planId: number; taskId: number; ids: number[] }, Rejected>(
  'runbook/setPredecessors', async ({ planId, taskId, ids }, { dispatch, rejectWithValue }) => {
    try { return await runbookService.setPredecessors(taskId, ids); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to update dependencies'));
    }
  });

export const transitionTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: TransitionRequest }, Rejected>(
  'runbook/transition', async ({ planId, taskId, body }, { dispatch, rejectWithValue }) => {
    try { return await runbookService.transition(taskId, body); }
    catch (err) {
      void dispatch(fetchRunbook(planId));
      return rejectWithValue(formatApiError(err, 'Failed to update task'));
    }
  });

/** A task's append-only history, newest first. Not stored in the slice: the
 * History dialog reads it fresh on every open. */
export const fetchTaskEvents = createAsyncThunk<RunbookTaskEventRead[], number, Rejected>(
  'runbook/events', async (taskId, { rejectWithValue }) => {
    try { return await runbookService.events(taskId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to load task history')); }
  });

const runbookSlice = createSlice({
  name: 'runbook',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchRunbooks.pending, (s, a) => { s.loading = true; delete s.listError[a.meta.arg]; });
    b.addCase(fetchRunbooks.fulfilled, (s, a) => { s.loading = false; s.plansByRelease[a.meta.arg] = a.payload; });
    b.addCase(fetchRunbooks.rejected, (s, a) => {
      s.loading = false;
      s.listError[a.meta.arg] = a.payload ?? 'Failed to load runbooks';
    });
    b.addCase(fetchRunbook.rejected, (s, a) => { s.refreshError[a.meta.arg] = a.payload ?? 'Failed to load runbook'; });
    b.addCase(deleteRunbook.fulfilled, (s, a) => {
      delete s.byPlan[a.payload.planId];
      delete s.loadedAt[a.payload.planId];
      delete s.refreshError[a.payload.planId];
      s.plansByRelease[a.payload.releaseId] =
        (s.plansByRelease[a.payload.releaseId] ?? []).filter((p) => p.id !== a.payload.planId);
    });
    for (const t of [fetchRunbook, createRunbook, updateRunbook, createTask, updateTask, deleteTask,
                     setPredecessors, transitionTask]) {
      b.addCase(t.fulfilled, (s, a) => {
        const read = a.payload as RunbookRead;
        s.byPlan[read.plan.id] = read;
        s.loadedAt[read.plan.id] = new Date().toISOString();
        delete s.refreshError[read.plan.id];
        const list = s.plansByRelease[read.plan.release_id];
        if (list) {
          const i = list.findIndex((p) => p.id === read.plan.id);
          if (i >= 0) list[i] = read.plan; else list.push(read.plan);
        }
      });
    }
  },
});
export default runbookSlice.reducer;
