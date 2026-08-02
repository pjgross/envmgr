import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { tenantAdminService } from '../services/tenantAdminService';
import type { TenantResponse, UserResponse } from '../types';

interface TenantAdminState {
  users: UserResponse[];
  /** Server-side total for `users`; greater than users.length means truncated. */
  usersTotal: number;
  settings: TenantResponse | null;
  loading: boolean;
  error: string | null;
}

export const fetchTenantSettings = createAsyncThunk('tenantAdmin/fetchSettings', () =>
  tenantAdminService.getSettings()
);
export const updateTenantSettings = createAsyncThunk(
  'tenantAdmin/updateSettings',
  (settings: Record<string, unknown>) => tenantAdminService.updateSettings(settings)
);
export const fetchUsers = createAsyncThunk('tenantAdmin/fetchUsers', () =>
  tenantAdminService.listUsers()
);
export const createUser = createAsyncThunk(
  'tenantAdmin/createUser',
  (data: { username: string; email: string; password: string; role?: string }) =>
    tenantAdminService.createUser(data)
);
export const updateUser = createAsyncThunk(
  'tenantAdmin/updateUser',
  ({ id, data }: { id: number; data: { username?: string; email?: string } }) =>
    tenantAdminService.updateUser(id, data)
);
export const setUserRole = createAsyncThunk(
  'tenantAdmin/setUserRole',
  ({ id, role }: { id: number; role: string }) => tenantAdminService.setUserRole(id, role)
);
export const deactivateUser = createAsyncThunk('tenantAdmin/deactivateUser', (id: number) =>
  tenantAdminService.deactivateUser(id)
);
export const reactivateUser = createAsyncThunk('tenantAdmin/reactivateUser', (id: number) =>
  tenantAdminService.reactivateUser(id)
);

const tenantAdminSlice = createSlice({
  name: 'tenantAdmin',
  initialState: { users: [], usersTotal: 0, settings: null, loading: false, error: null } as TenantAdminState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchTenantSettings.fulfilled, (state, action) => {
        state.settings = action.payload;
        state.loading = false;
      })
      .addCase(fetchTenantSettings.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchTenantSettings.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed';
      })
      .addCase(updateTenantSettings.fulfilled, (state, action) => {
        state.settings = action.payload;
        state.loading = false;
      })
      .addCase(updateTenantSettings.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(updateTenantSettings.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed';
      })
      .addCase(fetchUsers.fulfilled, (state, action) => {
        state.users = action.payload.rows;
        state.usersTotal = action.payload.total;
        state.loading = false;
      })
      .addCase(fetchUsers.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchUsers.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed';
      })
      .addCase(createUser.fulfilled, (state, action) => {
        state.users.push(action.payload);
        state.loading = false;
      })
      .addCase(createUser.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(createUser.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed';
      })
      .addCase(updateUser.fulfilled, (state, action) => {
        const idx = state.users.findIndex((u) => u.id === action.payload.id);
        if (idx !== -1) state.users[idx] = action.payload;
        state.loading = false;
      })
      .addCase(updateUser.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(updateUser.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed';
      })
      .addCase(setUserRole.fulfilled, (state, action) => {
        const idx = state.users.findIndex((u) => u.id === action.payload.id);
        if (idx !== -1) state.users[idx] = action.payload;
        state.loading = false;
      })
      .addCase(deactivateUser.fulfilled, (state, action) => {
        const idx = state.users.findIndex((u) => u.id === action.payload.id);
        if (idx !== -1) state.users[idx] = action.payload;
        state.loading = false;
      })
      .addCase(reactivateUser.fulfilled, (state, action) => {
        const idx = state.users.findIndex((u) => u.id === action.payload.id);
        if (idx !== -1) state.users[idx] = action.payload;
        state.loading = false;
      });
  },
});

export default tenantAdminSlice.reducer;
