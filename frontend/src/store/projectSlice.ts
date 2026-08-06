import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
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
  loading: boolean;
  error: string | null;
}

const initialState: ProjectState = {
  projects: [],
  total: 0,
  current: null,
  agreements: [],
  agreementTotal: 0,
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
      .addCase(fetchProject.fulfilled, (state, action) => {
        state.current = action.payload;
        // Neither this thunk nor the agreement fetches has a pending
        // handler, so without this a failed fetch's banner survives a later
        // successful one and sits on the detail page forever.
        state.error = null;
      })
      .addCase(fetchProject.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load project';
      })
      .addCase(fetchProjectAgreements.fulfilled, (state, action) => {
        state.agreements = action.payload.rows;
        state.agreementTotal = action.payload.total;
        state.error = null;
      })
      .addCase(fetchProjectAgreements.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load usage agreements';
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
