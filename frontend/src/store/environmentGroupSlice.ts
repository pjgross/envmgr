import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { environmentGroupService } from '../services/environmentGroupService';
import { formatApiError } from '../services/apiError';
import type {
  EnvironmentGroupCreate,
  EnvironmentGroupResponse,
  EnvironmentGroupUpdate,
  MemberCreate,
  MemberResponse,
} from '../types/environmentGroup';

interface EnvironmentGroupState {
  groups: EnvironmentGroupResponse[];
  total: number;
  // The single group backing the detail/admin page. Kept separate from
  // `groups` (a server-paged slice) so a deep link or refresh doesn't depend
  // on the list having been fetched first.
  current: EnvironmentGroupResponse | null;
  members: MemberResponse[];
  memberTotal: number;
  // The GROUP-detail read (fetchGroupMembers, "which environments belong to
  // this group"). `EnvironmentGroupDetail` owns this slot.
  //
  // `environmentGroups*` below is the mirror-image ENVIRONMENT-detail read
  // (fetchGroupsForEnvironment, "which groups is this environment a member
  // of" — EnvironmentGroupsPanel's "Member of" chips). It is deliberately a
  // SEPARATE field, not a second writer of `members`/`error`: those two
  // thunks are dispatched from two different pages that can be in flight at
  // once (the panel's chip links straight to the group detail page it would
  // otherwise collide with), and a shared slot means whichever response lands
  // last wins regardless of which page the user is actually looking at. See
  // the review finding on Task 10 for the reproduction.
  environmentGroups: MemberResponse[];
  environmentGroupsTotal: number;
  environmentGroupsError: string | null;
  // Guards fetchGroupsForEnvironment against a SAME-slot race: if
  // `environmentId` changes while a request is in flight, an older request's
  // response can still resolve after a newer one has already landed. Set to
  // the dispatching action's `meta.requestId` on `pending`; `fulfilled`/
  // `rejected` handlers ignore any response whose requestId no longer matches
  // — i.e. is not the most recently dispatched request for this slot.
  environmentGroupsRequestId: string | null;
  loading: boolean;
  error: string | null;
}

const initialState: EnvironmentGroupState = {
  groups: [],
  total: 0,
  current: null,
  members: [],
  memberTotal: 0,
  environmentGroups: [],
  environmentGroupsTotal: 0,
  environmentGroupsError: null,
  environmentGroupsRequestId: null,
  loading: false,
  error: null,
};

// Every thunk rejects with `rejectWithValue(formatApiError(...))` rather than
// letting the axios error escape. Redux Toolkit serialises an escaping error
// with miniSerializeError, which copies only name/message/stack/code —
// `response.data.detail`, where the backend puts its reason, is dropped, and a
// real AxiosError's `.message` is the generic "Request failed with status code
// 409". Consumers read `result.payload`, never `result.error.message`.

export const fetchEnvironmentGroups = createAsyncThunk<
  { rows: EnvironmentGroupResponse[]; total: number },
  Parameters<typeof environmentGroupService.listGroups>[0],
  { rejectValue: string }
>('environmentGroup/fetch', async (params, { rejectWithValue }) => {
  try {
    return await environmentGroupService.listGroups(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load environment groups'));
  }
});

export const fetchEnvironmentGroup = createAsyncThunk<
  EnvironmentGroupResponse,
  number,
  { rejectValue: string }
>('environmentGroup/fetchOne', async (id, { rejectWithValue }) => {
  try {
    return await environmentGroupService.getGroup(id);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load environment group'));
  }
});

export const createEnvironmentGroup = createAsyncThunk<
  EnvironmentGroupResponse,
  EnvironmentGroupCreate,
  { rejectValue: string }
>('environmentGroup/create', async (data, { rejectWithValue }) => {
  try {
    return await environmentGroupService.createGroup(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create environment group'));
  }
});

export const updateEnvironmentGroup = createAsyncThunk<
  EnvironmentGroupResponse,
  { id: number; data: EnvironmentGroupUpdate },
  { rejectValue: string }
>('environmentGroup/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await environmentGroupService.updateGroup(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update environment group'));
  }
});

export const deleteEnvironmentGroup = createAsyncThunk<number, number, { rejectValue: string }>(
  'environmentGroup/delete',
  async (id, { rejectWithValue }) => {
    try {
      await environmentGroupService.deleteGroup(id);
      return id;
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to delete environment group'));
    }
  }
);

export const fetchGroupMembers = createAsyncThunk<
  { rows: MemberResponse[]; total: number },
  number,
  { rejectValue: string }
>('environmentGroup/fetchMembers', async (groupId, { rejectWithValue }) => {
  try {
    return await environmentGroupService.listMembers(groupId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load group members'));
  }
});

export const fetchGroupsForEnvironment = createAsyncThunk<
  { rows: MemberResponse[]; total: number },
  number,
  { rejectValue: string }
>('environmentGroup/fetchForEnvironment', async (environmentId, { rejectWithValue }) => {
  try {
    return await environmentGroupService.listGroupsForEnvironment(environmentId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load environment groups'));
  }
});

export const addGroupMember = createAsyncThunk<
  MemberResponse,
  { groupId: number; data: MemberCreate },
  { rejectValue: string }
>('environmentGroup/addMember', async ({ groupId, data }, { rejectWithValue }) => {
  try {
    return await environmentGroupService.addMember(groupId, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to add group member'));
  }
});

export const removeGroupMember = createAsyncThunk<
  number,
  { groupId: number; memberId: number },
  { rejectValue: string }
>('environmentGroup/removeMember', async ({ groupId, memberId }, { rejectWithValue }) => {
  try {
    await environmentGroupService.removeMember(groupId, memberId);
    return memberId;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to remove group member'));
  }
});

const environmentGroupSlice = createSlice({
  name: 'environmentGroup',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchEnvironmentGroups.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchEnvironmentGroups.fulfilled, (state, action) => {
        state.loading = false;
        state.groups = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchEnvironmentGroups.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load environment groups';
      })
      .addCase(fetchEnvironmentGroup.pending, (state) => {
        state.current = null;
        state.error = null;
      })
      .addCase(fetchEnvironmentGroup.fulfilled, (state, action) => {
        state.current = action.payload;
        state.error = null;
      })
      .addCase(fetchEnvironmentGroup.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load environment group';
      })
      .addCase(fetchGroupMembers.pending, (state) => {
        state.members = [];
        state.memberTotal = 0;
        state.error = null;
      })
      .addCase(fetchGroupMembers.fulfilled, (state, action) => {
        state.members = action.payload.rows;
        state.memberTotal = action.payload.total;
        state.error = null;
      })
      .addCase(fetchGroupMembers.rejected, (state, action) => {
        state.error = action.payload ?? 'Failed to load group members';
      })
      .addCase(fetchGroupsForEnvironment.pending, (state, action) => {
        // Recorded so fulfilled/rejected below can tell a stale response from
        // the current one — see the field's docblock above.
        state.environmentGroupsRequestId = action.meta.requestId;
        state.environmentGroups = [];
        state.environmentGroupsTotal = 0;
        state.environmentGroupsError = null;
      })
      .addCase(fetchGroupsForEnvironment.fulfilled, (state, action) => {
        // A response for a request that is no longer the latest one dispatched
        // for this slot (environmentId changed again before this one landed)
        // is discarded rather than applied — applying it would overwrite the
        // newer environment's groups with the older one's.
        if (action.meta.requestId !== state.environmentGroupsRequestId) return;
        state.environmentGroups = action.payload.rows;
        state.environmentGroupsTotal = action.payload.total;
        state.environmentGroupsError = null;
      })
      .addCase(fetchGroupsForEnvironment.rejected, (state, action) => {
        if (action.meta.requestId !== state.environmentGroupsRequestId) return;
        state.environmentGroupsError = action.payload ?? 'Failed to load environment groups';
      });
    // Deliberately no fulfilled handlers for create/update/delete of groups,
    // or for add/remove of members: the lists are server-paged slices, and
    // splicing a row into or out of one desynchronises the page from its
    // total and from the sort order the server applied. The pages refetch
    // instead.
  },
});

export default environmentGroupSlice.reducer;
