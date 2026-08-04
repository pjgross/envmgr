import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { userGroupService } from '../services/userGroupService';
import { formatApiError } from '../services/apiError';
import type {
  UserGroupCreate,
  UserGroupMemberResponse,
  UserGroupResponse,
  UserGroupUpdate,
} from '../types/userGroup';

interface UserGroupState {
  groups: UserGroupResponse[];
  total: number;
  members: UserGroupMemberResponse[];
  memberTotal: number;
  loading: boolean;
  error: string | null;
}

const initialState: UserGroupState = {
  groups: [],
  total: 0,
  members: [],
  memberTotal: 0,
  loading: false,
  error: null,
};

// Every thunk rejects with `rejectWithValue(formatApiError(...))` rather than
// letting the axios error escape. Redux Toolkit serialises an escaping error
// with miniSerializeError, which copies only name/message/stack/code —
// `response.data.detail`, where the backend puts its reason, is dropped, and a
// real AxiosError's `.message` is the generic "Request failed with status code
// 409". Consumers read `result.payload`, never `result.error.message`.

export const fetchUserGroups = createAsyncThunk<
  { rows: UserGroupResponse[]; total: number },
  Parameters<typeof userGroupService.listGroups>[0],
  { rejectValue: string }
>('userGroup/fetch', async (params, { rejectWithValue }) => {
  try {
    return await userGroupService.listGroups(params);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load user groups'));
  }
});

export const createUserGroup = createAsyncThunk<
  UserGroupResponse,
  UserGroupCreate,
  { rejectValue: string }
>('userGroup/create', async (data, { rejectWithValue }) => {
  try {
    return await userGroupService.createGroup(data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to create user group'));
  }
});

export const updateUserGroup = createAsyncThunk<
  UserGroupResponse,
  { id: number; data: UserGroupUpdate },
  { rejectValue: string }
>('userGroup/update', async ({ id, data }, { rejectWithValue }) => {
  try {
    return await userGroupService.updateGroup(id, data);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to update user group'));
  }
});

export const deleteUserGroup = createAsyncThunk<number, number, { rejectValue: string }>(
  'userGroup/delete',
  async (id, { rejectWithValue }) => {
    try {
      await userGroupService.deleteGroup(id);
      return id;
    } catch (err) {
      return rejectWithValue(formatApiError(err, 'Failed to delete user group'));
    }
  }
);

export const fetchGroupMembers = createAsyncThunk<
  { rows: UserGroupMemberResponse[]; total: number },
  number,
  { rejectValue: string }
>('userGroup/fetchMembers', async (groupId, { rejectWithValue }) => {
  try {
    return await userGroupService.listMembers(groupId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load members'));
  }
});

export const addGroupMember = createAsyncThunk<
  UserGroupMemberResponse,
  { groupId: number; userId: number },
  { rejectValue: string }
>('userGroup/addMember', async ({ groupId, userId }, { rejectWithValue }) => {
  try {
    return await userGroupService.addMember(groupId, userId);
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to add member'));
  }
});

export const removeGroupMember = createAsyncThunk<
  number,
  { groupId: number; userId: number },
  { rejectValue: string }
>('userGroup/removeMember', async ({ groupId, userId }, { rejectWithValue }) => {
  try {
    await userGroupService.removeMember(groupId, userId);
    return userId;
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to remove member'));
  }
});

const userGroupSlice = createSlice({
  name: 'userGroup',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchUserGroups.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUserGroups.fulfilled, (state, action) => {
        state.loading = false;
        state.groups = action.payload.rows;
        // The server total, never rows.length — a page's length is not the set.
        state.total = action.payload.total;
      })
      .addCase(fetchUserGroups.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload ?? 'Failed to load user groups';
      })
      .addCase(fetchGroupMembers.fulfilled, (state, action) => {
        state.members = action.payload.rows;
        state.memberTotal = action.payload.total;
      })
      .addCase(addGroupMember.fulfilled, (state, action) => {
        state.members.push(action.payload);
        state.memberTotal += 1;
      })
      .addCase(removeGroupMember.fulfilled, (state, action) => {
        state.members = state.members.filter((m) => m.user_id !== action.payload);
        state.memberTotal -= 1;
      });
    // Deliberately no fulfilled handlers for create/update/delete of groups:
    // the list is a server-paged slice, and splicing a row into or out of it
    // desynchronises the page from its total. The pages refetch instead.
  },
});

export default userGroupSlice.reducer;
