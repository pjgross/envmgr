import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentRequestService } from '../services/environmentRequestService';
import { formatApiError } from '../services/apiError';
import type { EnvironmentResponse } from '../types/environment';
import type {
  AllowedTransition,
  EnvironmentHandoverUpdate,
  EnvironmentRequestCreate,
  EnvironmentRequestResponse,
  EnvironmentRequestUpdate,
  WelcomePack,
} from '../types/environmentRequest';

interface EnvironmentRequestState {
  requests: EnvironmentRequestResponse[];
  total: number;
  current: EnvironmentRequestResponse | null;
  allowedTransitions: AllowedTransition[];
  welcomePack: WelcomePack | null;
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentRequestState = {
  requests: [],
  total: 0,
  current: null,
  allowedTransitions: [],
  welcomePack: null,
  loading: false,
  error: null,
};

// Every thunk rejects with rejectWithValue(formatApiError(...)). Redux
// Toolkit's default miniSerializeError copies only name/message/stack/code, so
// response.data.detail — where this backend puts every 403 and 409 explanation
// — is discarded, and a real AxiosError's .message is the generic "Request
// failed with status code 403". Consumers read result.payload.

type Params = Parameters<typeof environmentRequestService.listRequests>[0];

export const fetchEnvironmentRequests = createAsyncThunk<
  { rows: EnvironmentRequestResponse[]; total: number },
  Params,
  { rejectValue: string }
>('environmentRequest/fetchAll', async (params, { rejectWithValue }) => {
  try {
    return await environmentRequestService.listRequests(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load requests'));
  }
});

export const fetchEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  number,
  { rejectValue: string }
>('environmentRequest/fetchOne', async (id, { rejectWithValue }) => {
  try {
    return await environmentRequestService.getRequest(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the request'));
  }
});

export const createEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  EnvironmentRequestCreate,
  { rejectValue: string }
>('environmentRequest/create', async (data, { rejectWithValue }) => {
  try {
    return await environmentRequestService.createRequest(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create the request'));
  }
});

export const updateEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  { id: number; data: EnvironmentRequestUpdate },
  { rejectValue: string }
>('environmentRequest/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.updateRequest(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update the request'));
  }
});

// No `notes` field: the backend's transition body is `{to_state}` only (see
// environmentRequestService.transition) — there is no history table for this
// entity, so `notes` would be accepted and silently discarded. Dropped here
// rather than threaded through and ignored.
export const transitionEnvironmentRequest = createAsyncThunk<
  EnvironmentRequestResponse,
  { id: number; toState: string },
  { rejectValue: string }
>('environmentRequest/transition', async ({ id, toState }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.transition(id, toState);
  } catch (err) {
    // The 403 here names WHY — "only the operating team ... can action this
    // request". Losing it leaves the user reading an HTTP status.
    return rejectWithValue(formatApiError(err, 'Failed to update the request state'));
  }
});

export const fetchAllowedTransitions = createAsyncThunk<
  AllowedTransition[],
  number,
  { rejectValue: string }
>('environmentRequest/allowedTransitions', async (id, { rejectWithValue }) => {
  try {
    return await environmentRequestService.allowedTransitions(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load available actions'));
  }
});

export const fetchWelcomePack = createAsyncThunk<WelcomePack, number, { rejectValue: string }>(
  'environmentRequest/welcomePack',
  async (id, { rejectWithValue }) => {
    try {
      return await environmentRequestService.getWelcomePack(id);
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to load the welcome pack'));
    }
  }
);

export const updateEnvironmentHandover = createAsyncThunk<
  EnvironmentResponse,
  { environmentId: number; data: EnvironmentHandoverUpdate },
  { rejectValue: string }
>('environmentRequest/handover', async ({ environmentId, data }, { rejectWithValue }) => {
  try {
    return await environmentRequestService.updateHandover(environmentId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to save the handover details'));
  }
});

const environmentRequestSlice = createSlice({
  name: 'environmentRequest',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchEnvironmentRequests.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchEnvironmentRequests.fulfilled, (state, action) => {
        state.loading = false;
        state.error = null;
        state.requests = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchEnvironmentRequests.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load requests';
      })
      .addCase(fetchEnvironmentRequest.fulfilled, (state, action) => {
        state.current = action.payload;
        state.error = null;
      })
      .addCase(fetchEnvironmentRequest.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load the request';
      })
      .addCase(transitionEnvironmentRequest.fulfilled, (state, action) => {
        // The detail page's own record, not the list — see the note below.
        state.current = action.payload;
      })
      .addCase(fetchAllowedTransitions.fulfilled, (state, action) => {
        state.allowedTransitions = action.payload;
      })
      .addCase(fetchWelcomePack.fulfilled, (state, action) => {
        state.welcomePack = action.payload;
        state.error = null;
      })
      .addCase(fetchWelcomePack.rejected, (state, action) => {
        state.welcomePack = null;
        state.error = action.payload ?? 'Failed to load the welcome pack';
      });
    // Deliberately NO fulfilled handler splicing `requests` for create, update
    // or transition: the list is one server-paged window, and local surgery
    // desynchronises the page from its total once a second page exists. The
    // pages re-dispatch fetchEnvironmentRequests instead.
  },
});

export default environmentRequestSlice.reducer;
