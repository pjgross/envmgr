import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';
import { runbookService } from '../services/runbookService';
import { formatApiError } from '../services/apiError';
import type {
  RunbookPlanCreate, RunbookPlanRead, RunbookPlanUpdate, RunbookRead, RunbookTaskCreate,
  RunbookTaskUpdate, TransitionRequest,
} from '../types/runbook';

interface RunbookState {
  plansByRelease: Record<number, RunbookPlanRead[]>;
  byPlan: Record<number, RunbookRead>;
  loading: boolean;
  error: string | null;
}
const initialState: RunbookState = { plansByRelease: {}, byPlan: {}, loading: false, error: null };
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
export const createRunbook = createAsyncThunk<RunbookRead, { releaseId: number; body: RunbookPlanCreate }, Rejected>(
  'runbook/create', async ({ releaseId, body }, { rejectWithValue }) => {
    try { return await runbookService.create(releaseId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to create runbook')); }
  });

export const updateRunbook = createAsyncThunk<RunbookRead, { planId: number; body: RunbookPlanUpdate }, Rejected>(
  'runbook/update', async ({ planId, body }, { rejectWithValue }) => {
    try { return await runbookService.update(planId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update runbook')); }
  });

export const deleteRunbook = createAsyncThunk<{ releaseId: number; planId: number }, { releaseId: number; planId: number }, Rejected>(
  'runbook/delete', async (arg, { rejectWithValue }) => {
    try { await runbookService.remove(arg.planId); return arg; }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to delete runbook')); }
  });

export const createTask = createAsyncThunk<RunbookRead, { planId: number; body: RunbookTaskCreate }, Rejected>(
  'runbook/createTask', async ({ planId, body }, { rejectWithValue }) => {
    try { await runbookService.createTask(planId, body); return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to add task')); }
  });

export const updateTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: RunbookTaskUpdate }, Rejected>(
  'runbook/updateTask', async ({ taskId, body }, { rejectWithValue }) => {
    try { return await runbookService.updateTask(taskId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update task')); }
  });

export const deleteTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number }, Rejected>(
  'runbook/deleteTask', async ({ planId, taskId }, { rejectWithValue }) => {
    try { await runbookService.removeTask(taskId); return await runbookService.get(planId); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to delete task')); }
  });

export const setPredecessors = createAsyncThunk<RunbookRead, { planId: number; taskId: number; ids: number[] }, Rejected>(
  'runbook/setPredecessors', async ({ taskId, ids }, { rejectWithValue }) => {
    try { return await runbookService.setPredecessors(taskId, ids); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update dependencies')); }
  });

export const transitionTask = createAsyncThunk<RunbookRead, { planId: number; taskId: number; body: TransitionRequest }, Rejected>(
  'runbook/transition', async ({ taskId, body }, { rejectWithValue }) => {
    try { return await runbookService.transition(taskId, body); }
    catch (err) { return rejectWithValue(formatApiError(err, 'Failed to update task')); }
  });

const runbookSlice = createSlice({
  name: 'runbook',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchRunbooks.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchRunbooks.fulfilled, (s, a) => { s.loading = false; s.plansByRelease[a.meta.arg] = a.payload; });
    b.addCase(fetchRunbooks.rejected, (s, a) => { s.loading = false; s.error = a.payload ?? 'Failed to load runbooks'; });
    b.addCase(fetchRunbook.rejected, (s, a) => { s.error = a.payload ?? 'Failed to load runbook'; });
    b.addCase(deleteRunbook.fulfilled, (s, a) => {
      delete s.byPlan[a.payload.planId];
      s.plansByRelease[a.payload.releaseId] =
        (s.plansByRelease[a.payload.releaseId] ?? []).filter((p) => p.id !== a.payload.planId);
    });
    for (const t of [fetchRunbook, createRunbook, updateRunbook, createTask, updateTask, deleteTask,
                     setPredecessors, transitionTask]) {
      b.addCase(t.fulfilled, (s, a) => {
        const read = a.payload as RunbookRead;
        s.byPlan[read.plan.id] = read;
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
