import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type {
  ReleaseResponse,
  ReleaseListItemResponse,
  ReleaseCreatePayload,
  ReleaseUpdatePayload,
  ReleaseTransitionPayload,
  ReleaseListFilters,
  ReleaseStatusHistory,
  TestPhaseResponse,
  TestPhaseCreatePayload,
  TestPhaseUpdatePayload,
  ReleaseGateResponse,
  ReleaseGateCreatePayload,
  ReleaseGateUpdatePayload,
  ReleaseGateDecisionPayload,
  ReleaseDependencyResponse,
  ReleaseDependencyCreatePayload,
  ReleaseDependencyAlert,
  ReleaseCalendarEntry,
  ReleaseTimelineEntry,
} from '../types/release';
import type {
  GateCriterionCreatePayload,
  GateCriterionUpdatePayload,
} from '../types/gateCriterion';
import type { ReleaseEventResponse, ReleaseEventCreatePayload } from '../types/releaseEvent';
import type {
  ReleaseChangeResponse,
  ReleaseChangeCreatePayload,
  ReleaseChangeUpdatePayload,
  ReleaseChangeMovePayload,
  ReleaseChangeReleaseHistoryResponse,
  ReleaseChangeStatusHistoryResponse,
} from '../types/releaseChange';
import { releaseService } from '../services/releaseService';

interface ReleaseState {
  list: ReleaseListItemResponse[];
  total: number;
  detail: ReleaseResponse | null;
  loading: boolean;
  /**
   * The list query's own flag. `loading` is shared by ~20 thunks, and an
   * aborted list request on unmount has no successor to clear it — isolating
   * the list keeps that from hanging every other consumer of the slice.
   */
  listLoading: boolean;
  error: string | null;
  filters: ReleaseListFilters;
  phases: TestPhaseResponse[];
  gates: ReleaseGateResponse[];
  dependencies: ReleaseDependencyResponse[];
  dependencyAlerts: ReleaseDependencyAlert[];
  events: ReleaseEventResponse[];
  changes: ReleaseChangeResponse[];
  backlog: ReleaseChangeResponse[];
  changeReleaseHistory: ReleaseChangeReleaseHistoryResponse[];
  changeStatusHistory: ReleaseChangeStatusHistoryResponse[];
  history: ReleaseStatusHistory[];
  calendar: ReleaseCalendarEntry[];
  timeline: ReleaseTimelineEntry[];
}

const initialState: ReleaseState = {
  list: [],
  total: 0,
  detail: null,
  loading: false,
  listLoading: false,
  error: null,
  filters: {},
  phases: [],
  gates: [],
  dependencies: [],
  dependencyAlerts: [],
  events: [],
  changes: [],
  backlog: [],
  changeReleaseHistory: [],
  changeStatusHistory: [],
  history: [],
  calendar: [],
  timeline: [],
};

// --- Release CRUD ---
export const fetchReleases = createAsyncThunk(
  'release/list',
  (filters: ReleaseListFilters = {}) => releaseService.list(filters)
);

export const fetchRelease = createAsyncThunk('release/get', (id: number) =>
  releaseService.get(id)
);

export const createRelease = createAsyncThunk(
  'release/create',
  (data: ReleaseCreatePayload) => releaseService.create(data)
);

export const updateRelease = createAsyncThunk(
  'release/update',
  ({ id, data }: { id: number; data: ReleaseUpdatePayload }) => releaseService.update(id, data)
);

export const transitionRelease = createAsyncThunk(
  'release/transition',
  ({ id, data }: { id: number; data: ReleaseTransitionPayload }) =>
    releaseService.transition(id, data)
);

export const deleteRelease = createAsyncThunk('release/delete', (id: number) =>
  releaseService.remove(id).then(() => id)
);

export const fetchReleaseHistory = createAsyncThunk('release/history', (id: number) =>
  releaseService.listHistory(id)
);

// --- Calendar / Timeline ---
export const fetchReleaseCalendar = createAsyncThunk(
  'release/calendar',
  ({ from, to }: { from: string; to: string }) => releaseService.listCalendar(from, to)
);

export const fetchReleaseTimeline = createAsyncThunk(
  'release/timeline',
  (filters: ReleaseListFilters = {}) => releaseService.listTimeline(filters)
);

// --- Phases ---
export const fetchPhases = createAsyncThunk('release/listPhases', (releaseId: number) =>
  releaseService.listPhases(releaseId)
);

export const createPhase = createAsyncThunk(
  'release/createPhase',
  ({ releaseId, data }: { releaseId: number; data: TestPhaseCreatePayload }) =>
    releaseService.createPhase(releaseId, data)
);

export const updatePhase = createAsyncThunk(
  'release/updatePhase',
  ({ releaseId, phaseId, data }: { releaseId: number; phaseId: number; data: TestPhaseUpdatePayload }) =>
    releaseService.updatePhase(releaseId, phaseId, data)
);

export const deletePhase = createAsyncThunk(
  'release/deletePhase',
  ({ releaseId, phaseId }: { releaseId: number; phaseId: number }) =>
    releaseService.deletePhase(releaseId, phaseId).then(() => phaseId)
);

// --- Gates ---
export const fetchGates = createAsyncThunk('release/listGates', (releaseId: number) =>
  releaseService.listGates(releaseId)
);

export const createGate = createAsyncThunk(
  'release/createGate',
  ({ releaseId, data }: { releaseId: number; data: ReleaseGateCreatePayload }) =>
    releaseService.createGate(releaseId, data)
);

export const updateGate = createAsyncThunk(
  'release/updateGate',
  ({ releaseId, gateId, data }: { releaseId: number; gateId: number; data: ReleaseGateUpdatePayload }) =>
    releaseService.updateGate(releaseId, gateId, data)
);

export const deleteGate = createAsyncThunk(
  'release/deleteGate',
  async ({ releaseId, gateId }: { releaseId: number; gateId: number }) => {
    await releaseService.deleteGate(releaseId, gateId);
    return gateId;
  }
);

export const passGate = createAsyncThunk(
  'release/passGate',
  ({ releaseId, gateId, data }: { releaseId: number; gateId: number; data?: ReleaseGateDecisionPayload }) =>
    releaseService.passGate(releaseId, gateId, data)
);

export const failGate = createAsyncThunk(
  'release/failGate',
  ({ releaseId, gateId, data }: { releaseId: number; gateId: number; data?: ReleaseGateDecisionPayload }) =>
    releaseService.failGate(releaseId, gateId, data)
);

export const overrideGate = createAsyncThunk(
  'release/overrideGate',
  ({ releaseId, gateId, data }: { releaseId: number; gateId: number; data?: ReleaseGateDecisionPayload }) =>
    releaseService.overrideGate(releaseId, gateId, data)
);

// --- Gate Criteria ---
export const createCriterion = createAsyncThunk(
  'release/createCriterion',
  async (args: { releaseId: number; gateId: number; payload: GateCriterionCreatePayload }) =>
    releaseService.createCriterion(args.releaseId, args.gateId, args.payload),
);

export const updateCriterion = createAsyncThunk(
  'release/updateCriterion',
  async (args: { criterionId: number; payload: GateCriterionUpdatePayload }) =>
    releaseService.updateCriterion(args.criterionId, args.payload),
);

export const completeCriterion = createAsyncThunk(
  'release/completeCriterion',
  async (criterionId: number) => releaseService.completeCriterion(criterionId),
);

export const reopenCriterion = createAsyncThunk(
  'release/reopenCriterion',
  async (criterionId: number) => releaseService.reopenCriterion(criterionId),
);

export const deleteCriterion = createAsyncThunk(
  'release/deleteCriterion',
  async (criterionId: number) => {
    await releaseService.deleteCriterion(criterionId);
    return criterionId;
  },
);

// --- Dependencies ---
export const fetchDependencies = createAsyncThunk('release/listDependencies', (releaseId: number) =>
  releaseService.listDependencies(releaseId)
);

export const addDependency = createAsyncThunk(
  'release/addDependency',
  ({ releaseId, data }: { releaseId: number; data: ReleaseDependencyCreatePayload }) =>
    releaseService.addDependency(releaseId, data)
);

export const removeDependency = createAsyncThunk(
  'release/removeDependency',
  (releaseDependencyId: number) =>
    releaseService.removeDependency(releaseDependencyId).then(() => releaseDependencyId)
);

export const fetchDependencyAlerts = createAsyncThunk('release/dependencyAlerts', (releaseId: number) =>
  releaseService.listDependencyAlerts(releaseId)
);

export const acknowledgeAlert = createAsyncThunk(
  'release/acknowledgeAlert',
  ({ releaseId, dependencyId }: { releaseId: number; dependencyId: number }) =>
    releaseService.acknowledgeAlert(releaseId, dependencyId).then(() => dependencyId)
);

// --- Events ---
export const fetchReleaseEvents = createAsyncThunk('release/listEvents', (releaseId: number) =>
  releaseService.listEvents(releaseId)
);

export const createReleaseEvent = createAsyncThunk(
  'release/createEvent',
  ({ releaseId, data }: { releaseId: number; data: ReleaseEventCreatePayload }) =>
    releaseService.createEvent(releaseId, data)
);

// --- Changes ---
export const fetchReleaseChanges = createAsyncThunk('release/listChanges', (releaseId: number) =>
  releaseService.listChanges(releaseId)
);

export const createReleaseChange = createAsyncThunk(
  'release/createChange',
  ({ releaseId, data }: { releaseId: number; data: ReleaseChangeCreatePayload }) =>
    releaseService.createChange(releaseId, data)
);

export const updateReleaseChange = createAsyncThunk(
  'release/updateChange',
  ({ changeId, data }: { changeId: number; data: ReleaseChangeUpdatePayload }) =>
    releaseService.updateChange(changeId, data)
);

export const deleteReleaseChange = createAsyncThunk(
  'release/deleteChange',
  (changeId: number) => releaseService.deleteChange(changeId).then(() => changeId)
);

export const moveReleaseChange = createAsyncThunk(
  'release/moveChange',
  ({ changeId, payload }: { changeId: number; payload: ReleaseChangeMovePayload }) =>
    releaseService.moveReleaseChange(changeId, payload)
);

export const fetchBacklogChanges = createAsyncThunk(
  'release/listBacklog',
  () => releaseService.listBacklogChanges()
);

export const fetchReleaseChangeReleaseHistory = createAsyncThunk(
  'release/changeReleaseHistory',
  (changeId: number) => releaseService.fetchReleaseChangeReleaseHistory(changeId)
);

export const fetchReleaseChangeStatusHistory = createAsyncThunk(
  'release/changeStatusHistory',
  (changeId: number) => releaseService.fetchReleaseChangeStatusHistory(changeId)
);

const releaseSlice = createSlice({
  name: 'release',
  initialState,
  reducers: {
    clearDetail(state) {
      state.detail = null;
      state.phases = [];
      state.gates = [];
      state.dependencies = [];
      state.dependencyAlerts = [];
      state.events = [];
      state.changes = [];
      state.history = [];
    },
  },
  extraReducers: (builder) => {
    builder
      // list
      .addCase(fetchReleases.pending, (state) => { state.listLoading = true; state.error = null; })
      .addCase(fetchReleases.fulfilled, (state, action) => {
        state.listLoading = false;
        state.list = action.payload.rows;
        state.total = action.payload.total;
      })
      .addCase(fetchReleases.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than merely
        // ignoring its reply. RTK dispatches `pending` for the new request
        // synchronously, then `rejected` for the aborted one on a
        // microtask — so without this guard, `listLoading` would flip back to
        // false (the grid's spinner flickers off) and `error` would be set
        // to 'Aborted' while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to load releases';
      })

      // get
      .addCase(fetchRelease.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchRelease.fulfilled, (state, action) => { state.loading = false; state.detail = action.payload; })
      .addCase(fetchRelease.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed to load release'; })

      // create — counts default to 0 for a brand-new release
      .addCase(createRelease.fulfilled, (state, action) => {
        state.list.unshift({
          ...action.payload,
          phase_count: 0,
          scope_count: 0,
          blocker_count: 0,
          overdue_criterion_count: 0,
          scope_additions_count: 0,
          scope_removals_count: 0,
          scope_change_count: 0,
          scope_creep_count: 0,
          window_status: 'no_cutoff',
          days_to_cutoff: null,
          systems: [],
        });
        state.total += 1;
      })

      // update — preserve existing counts, merge updated fields
      .addCase(updateRelease.fulfilled, (state, action) => {
        const idx = state.list.findIndex((r) => r.id === action.payload.id);
        if (idx !== -1) state.list[idx] = { ...state.list[idx], ...action.payload };
        if (state.detail?.id === action.payload.id) state.detail = action.payload;
      })

      // transition — preserve existing counts, update status/fields
      .addCase(transitionRelease.fulfilled, (state, action) => {
        const idx = state.list.findIndex((r) => r.id === action.payload.id);
        if (idx !== -1) state.list[idx] = { ...state.list[idx], ...action.payload };
        if (state.detail?.id === action.payload.id) state.detail = action.payload;
      })

      // delete
      .addCase(deleteRelease.fulfilled, (state, action) => {
        state.list = state.list.filter((r) => r.id !== action.payload);
        state.total = Math.max(0, state.total - 1);
        if (state.detail?.id === action.payload) state.detail = null;
      })

      // history
      .addCase(fetchReleaseHistory.fulfilled, (state, action) => { state.history = action.payload; })

      // calendar / timeline — these thunks are not wired to useServerGrid's
      // abort mechanism (ReleaseCalendar/ReleaseTimeline dispatch directly
      // in a plain useEffect), but they still need ordinary pending/rejected
      // loading transitions: without them, `loading` never turns true (so
      // the spinner never shows) and never turns false on failure.
      .addCase(fetchReleaseCalendar.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchReleaseCalendar.fulfilled, (state, action) => {
        state.loading = false;
        state.calendar = action.payload;
      })
      .addCase(fetchReleaseCalendar.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load calendar';
      })
      .addCase(fetchReleaseTimeline.pending, (state) => { state.loading = true; state.error = null; })
      .addCase(fetchReleaseTimeline.fulfilled, (state, action) => {
        state.loading = false;
        state.timeline = action.payload;
      })
      .addCase(fetchReleaseTimeline.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load timeline';
      })

      // phases
      .addCase(fetchPhases.fulfilled, (state, action) => { state.phases = action.payload; })
      .addCase(createPhase.fulfilled, (state, action) => { state.phases.push(action.payload); })
      .addCase(updatePhase.fulfilled, (state, action) => {
        const idx = state.phases.findIndex((p) => p.id === action.payload.id);
        if (idx !== -1) state.phases[idx] = action.payload;
      })
      .addCase(deletePhase.fulfilled, (state, action) => {
        state.phases = state.phases.filter((p) => p.id !== action.payload);
      })

      // gates
      .addCase(fetchGates.fulfilled, (state, action) => { state.gates = action.payload; })
      .addCase(createGate.fulfilled, (state, action) => { state.gates.push(action.payload); })
      .addCase(updateGate.fulfilled, (state, action) => {
        const idx = state.gates.findIndex((g) => g.id === action.payload.id);
        if (idx !== -1) state.gates[idx] = action.payload;
      })
      .addCase(passGate.fulfilled, (state, action) => {
        const idx = state.gates.findIndex((g) => g.id === action.payload.id);
        if (idx !== -1) state.gates[idx] = action.payload;
      })
      .addCase(failGate.fulfilled, (state, action) => {
        const idx = state.gates.findIndex((g) => g.id === action.payload.id);
        if (idx !== -1) state.gates[idx] = action.payload;
      })
      .addCase(overrideGate.fulfilled, (state, action) => {
        const idx = state.gates.findIndex((g) => g.id === action.payload.id);
        if (idx !== -1) state.gates[idx] = action.payload;
      })

      // criteria
      .addCase(createCriterion.fulfilled, (state, action) => {
        const crit = action.payload;
        const gate = state.gates.find((g) => g.id === crit.gate_id);
        if (gate) gate.criteria.push(crit);
      })
      .addCase(updateCriterion.fulfilled, (state, action) => {
        const crit = action.payload;
        const gate = state.gates.find((g) => g.id === crit.gate_id);
        if (!gate) return;
        const i = gate.criteria.findIndex((c) => c.id === crit.id);
        if (i >= 0) gate.criteria[i] = crit;
      })
      .addCase(completeCriterion.fulfilled, (state, action) => {
        const crit = action.payload;
        const gate = state.gates.find((g) => g.id === crit.gate_id);
        if (!gate) return;
        const i = gate.criteria.findIndex((c) => c.id === crit.id);
        if (i >= 0) gate.criteria[i] = crit;
        // Auto-pass may have flipped gate.status — calling component must dispatch fetchGates(releaseId).
      })
      .addCase(reopenCriterion.fulfilled, (state, action) => {
        const crit = action.payload;
        const gate = state.gates.find((g) => g.id === crit.gate_id);
        if (!gate) return;
        const i = gate.criteria.findIndex((c) => c.id === crit.id);
        if (i >= 0) gate.criteria[i] = crit;
      })
      .addCase(deleteCriterion.fulfilled, (state, action) => {
        const criterionId = action.payload;
        state.gates.forEach((gate) => {
          gate.criteria = gate.criteria.filter((c) => c.id !== criterionId);
        });
      })

      // dependencies
      .addCase(fetchDependencies.fulfilled, (state, action) => { state.dependencies = action.payload; })
      .addCase(addDependency.fulfilled, (state, action) => { state.dependencies.push(action.payload); })
      .addCase(removeDependency.fulfilled, (state, action) => {
        state.dependencies = state.dependencies.filter((d) => d.id !== action.payload);
      })
      .addCase(fetchDependencyAlerts.fulfilled, (state, action) => { state.dependencyAlerts = action.payload; })
      .addCase(acknowledgeAlert.fulfilled, (state, action) => {
        state.dependencyAlerts = state.dependencyAlerts.filter((a) => a.dependency_id !== action.payload);
      })

      // events
      .addCase(fetchReleaseEvents.fulfilled, (state, action) => { state.events = action.payload; })
      .addCase(createReleaseEvent.fulfilled, (state, action) => { state.events.push(action.payload); })

      // changes
      .addCase(fetchReleaseChanges.fulfilled, (state, action) => { state.changes = action.payload; })
      .addCase(createReleaseChange.fulfilled, (state, action) => { state.changes.push(action.payload); })
      .addCase(updateReleaseChange.fulfilled, (state, action) => {
        const idx = state.changes.findIndex((c) => c.id === action.payload.id);
        if (idx !== -1) state.changes[idx] = action.payload;
      })
      .addCase(deleteReleaseChange.fulfilled, (state, action) => {
        state.changes = state.changes.filter((c) => c.id !== action.payload);
      })

      // move change — update in-state row if found; remove from backlog if it was there
      .addCase(moveReleaseChange.fulfilled, (state, action) => {
        const updated = action.payload;
        const idx = state.changes.findIndex((c) => c.id === updated.id);
        if (idx !== -1) state.changes[idx] = updated;
        state.backlog = state.backlog.filter((c) => c.id !== updated.id);
      })

      // backlog
      .addCase(fetchBacklogChanges.fulfilled, (state, action) => { state.backlog = action.payload; })

      // change history
      .addCase(fetchReleaseChangeReleaseHistory.fulfilled, (state, action) => {
        state.changeReleaseHistory = action.payload;
      })
      .addCase(fetchReleaseChangeStatusHistory.fulfilled, (state, action) => {
        state.changeStatusHistory = action.payload;
      });
  },
});

export const { clearDetail } = releaseSlice.actions;
export default releaseSlice.reducer;
