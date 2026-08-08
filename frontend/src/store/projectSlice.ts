import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { bookingService } from '../services/bookingService';
import { projectService } from '../services/projectService';
import { formatApiError } from '../services/apiError';
import type {
  ProjectCreate,
  ProjectResponse,
  ProjectUpdate,
  UsageAgreementCreate,
  UsageAgreementResponse,
} from '../types/project';

interface ProjectState {
  projects: ProjectResponse[];
  total: number;
  // The single project backing the detail/admin page. Kept separate from
  // `projects` (a server-paged slice) so a deep link or refresh doesn't
  // depend on the list having been fetched first.
  current: ProjectResponse | null;
  agreements: UsageAgreementResponse[];
  agreementTotal: number;
  /**
   * How many of this project's bookings are currently in a usage-agreement
   * gap (Phase 7 A3), or null when it has not been loaded — or could not be.
   *
   * null is NOT zero, and the page must not render it as "no gaps": a count
   * nobody could compute reading as a clean bill of health is the
   * partial-read trap CLAUDE.md records against the drift dialog. Hence the
   * separate error below rather than a fall back to 0.
   */
  gapBookingCount: number | null;
  /**
   * Why the count above is null, when the reason was a refusal rather than
   * "not asked yet". Deliberately NOT folded into `error`: that banner is the
   * project/agreements load, and a failed rollup must not read as a failed
   * page.
   */
  gapBookingCountError: string | null;
  loading: boolean;
  error: string | null;
}

const initialState: ProjectState = {
  projects: [],
  total: 0,
  current: null,
  agreements: [],
  agreementTotal: 0,
  gapBookingCount: null,
  gapBookingCountError: null,
  loading: false,
  error: null,
};

// Every thunk rejects with `rejectWithValue(formatApiError(...))` rather than
// letting the axios error escape. Redux Toolkit serialises an escaping error
// with miniSerializeError, which copies only name/message/stack/code —
// `response.data.detail`, where the backend puts its reason, is dropped, and a
// real AxiosError's `.message` is the generic "Request failed with status code
// 409". Consumers read `result.payload`, never `result.error.message`.

export const fetchProjects = createAsyncThunk<
  { rows: ProjectResponse[]; total: number },
  Parameters<typeof projectService.listProjects>[0],
  { rejectValue: string }
>('project/fetch', async (params, { rejectWithValue }) => {
  try {
    return await projectService.listProjects(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load projects'));
  }
});

export const fetchProject = createAsyncThunk<ProjectResponse, number, { rejectValue: string }>(
  'project/fetchOne',
  async (id, { rejectWithValue }) => {
    try {
      return await projectService.getProject(id);
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to load project'));
    }
  }
);

export const createProject = createAsyncThunk<
  ProjectResponse,
  ProjectCreate,
  { rejectValue: string }
>('project/create', async (data, { rejectWithValue }) => {
  try {
    return await projectService.createProject(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create project'));
  }
});

export const updateProject = createAsyncThunk<
  ProjectResponse,
  { id: number; data: ProjectUpdate },
  { rejectValue: string }
>('project/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await projectService.updateProject(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update project'));
  }
});

export const deleteProject = createAsyncThunk<number, number, { rejectValue: string }>(
  'project/delete',
  async (id, { rejectWithValue }) => {
    try {
      await projectService.deleteProject(id);
      return id;
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to delete project'));
    }
  }
);

export const fetchProjectAgreements = createAsyncThunk<
  { rows: UsageAgreementResponse[]; total: number },
  number,
  { rejectValue: string }
>('project/fetchAgreements', async (projectId, { rejectWithValue }) => {
  try {
    return await projectService.listAgreementsForProject(projectId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load usage agreements'));
  }
});

/**
 * How many of one project's bookings are currently in a usage-agreement gap
 * (Phase 7 A3) — the number, without the rows.
 *
 * THERE IS NO COUNT ENDPOINT AND THIS DOES NOT ADD ONE. `GET /bookings` is
 * `pagination()`-bound and answers with `X-Total-Count`, the total for the
 * FILTERED set rather than for the returned window, so a `limit: 1` request
 * yields the count for one row's worth of work. `listBookings` already reads
 * that header (`services/bookingService.ts`).
 *
 * The parameters are byte-for-byte the ones behind ProjectDetail's link to
 * `/bookings/list?project_id=…&agreement_gap=true`, which is the whole point:
 * the count and the list the user lands on are ONE query with one window, so
 * they cannot disagree. Both names are real — `list_bookings` in
 * `backend/app/api/v1/bookings.py` declares `project_id` and `agreement_gap`
 * — and that matters because FastAPI drops an unknown query param SILENTLY:
 * A1 shipped a count linking to a `?project_id=` filter `GET /environments`
 * never had, and it showed the whole estate as one project's environments
 * with a test and the admin guide both asserting it as correct.
 *
 * Note the count spans every lifecycle status, drafts and closed bookings
 * included — `gap_clause` filters on the project and the agreement, never on
 * `Booking.status`. The linked list shows exactly the same set for the same
 * reason.
 */
export const fetchProjectGapBookingCount = createAsyncThunk<
  number,
  number,
  { rejectValue: string }
>('project/fetchGapBookingCount', async (projectId, { rejectWithValue }) => {
  try {
    const { total } = await bookingService.listBookings({
      project_id: projectId,
      agreement_gap: true,
      // The smallest window `pagination()` allows (`ge=1`). We want the
      // header, not the rows.
      limit: 1,
    });
    return total;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to count bookings in gap'));
  }
});

export const fetchEnvironmentAgreements = createAsyncThunk<
  { rows: UsageAgreementResponse[]; total: number },
  number,
  { rejectValue: string }
>('project/fetchEnvironmentAgreements', async (environmentId, { rejectWithValue }) => {
  try {
    return await projectService.listAgreementsForEnvironment(environmentId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load usage agreements'));
  }
});

export const createUsageAgreement = createAsyncThunk<
  UsageAgreementResponse,
  { projectId: number; data: UsageAgreementCreate },
  { rejectValue: string }
>('project/createAgreement', async ({ projectId, data }, { rejectWithValue }) => {
  try {
    return await projectService.createAgreement(projectId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create usage agreement'));
  }
});

export const deleteUsageAgreement = createAsyncThunk<
  number,
  { projectId: number; agreementId: number },
  { rejectValue: string }
>('project/deleteAgreement', async ({ projectId, agreementId }, { rejectWithValue }) => {
  try {
    await projectService.deleteAgreement(projectId, agreementId);
    return agreementId;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to delete usage agreement'));
  }
});

const projectSlice = createSlice({
  name: 'project',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchProjects.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchProjects.fulfilled, (state, action) => {
        state.loading = false;
        state.projects = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchProjects.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load projects';
      })
      // Finding I3: state.project.current and state.agreements are each
      // shared between call sites that are one click apart —
      // fetchProjectAgreements (project direction) and
      // fetchEnvironmentAgreements (environment direction) both write
      // `agreements`, and navigating project A -> B both write `current`.
      // Without a `pending` handler, mounting the SECOND consumer while the
      // FIRST's data is still in state renders that stale data as though it
      // belonged to the new entity — e.g. EnvironmentProjectsPanel showing a
      // project's agreements for environments that are not the one it was
      // asked about, or ProjectDetail flashing the previous project's name.
      // Clearing on `pending` also clears `error` on all three, so a stale
      // banner cannot survive under a freshly (and successfully) rendered
      // table either.
      .addCase(fetchProject.pending, (state) => {
        state.current = null;
        state.error = null;
      })
      .addCase(fetchProject.fulfilled, (state, action) => {
        state.current = action.payload;
        state.error = null;
      })
      .addCase(fetchProject.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load project';
      })
      .addCase(fetchProjectAgreements.pending, (state) => {
        state.agreements = [];
        state.agreementTotal = 0;
        state.error = null;
      })
      .addCase(fetchProjectAgreements.fulfilled, (state, action) => {
        state.agreements = action.payload.rows;
        state.agreementTotal = action.payload.total;
        state.error = null;
      })
      .addCase(fetchProjectAgreements.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load usage agreements';
      })
      // Same reasoning as fetchProject's pending handler above: `current` and
      // this count are one project's, and navigating project A -> B must not
      // render A's rollup under B's name for as long as the second request
      // takes. Clearing on pending also clears the previous failure, so a
      // stale "unavailable" caption cannot survive a successful reload.
      .addCase(fetchProjectGapBookingCount.pending, (state) => {
        state.gapBookingCount = null;
        state.gapBookingCountError = null;
      })
      .addCase(fetchProjectGapBookingCount.fulfilled, (state, action) => {
        state.gapBookingCount = action.payload;
        state.gapBookingCountError = null;
      })
      .addCase(fetchProjectGapBookingCount.rejected, (state, action) => {
        // `gapBookingCount` stays null. Never 0 — see the field's JSDoc: a
        // count nobody could compute must not read as "no gaps".
        state.gapBookingCountError = action.payload ?? 'Failed to count bookings in gap';
      })
      .addCase(fetchEnvironmentAgreements.pending, (state) => {
        state.agreements = [];
        state.agreementTotal = 0;
        state.error = null;
      })
      .addCase(fetchEnvironmentAgreements.fulfilled, (state, action) => {
        state.agreements = action.payload.rows;
        state.agreementTotal = action.payload.total;
        state.error = null;
      })
      .addCase(fetchEnvironmentAgreements.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load usage agreements';
      });
    // Deliberately no fulfilled handlers for create/update/delete of projects,
    // or for create/delete of usage agreements: the lists are server-paged
    // slices, and splicing a row into or out of one desynchronises the page
    // from its total. The pages refetch instead.
  },
});

export default projectSlice.reducer;
