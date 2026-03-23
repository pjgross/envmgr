import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { adminService } from '../services/adminService'
import { enterImpersonation } from './authSlice'
import type { TenantResponse, UserResponse } from '../types'
import type { AppDispatch } from './index'

interface AdminState {
  tenants: TenantResponse[]
  tenantUsers: UserResponse[]
  loading: boolean
  error: string | null
}

export const fetchTenants = createAsyncThunk('admin/fetchTenants', () => adminService.listTenants())
export const createTenant = createAsyncThunk('admin/createTenant', (data: { name: string; slug: string }) => adminService.createTenant(data))
export const disableTenant = createAsyncThunk('admin/disableTenant', (id: number) => adminService.disableTenant(id))
export const fetchTenantUsers = createAsyncThunk('admin/fetchTenantUsers', (tenantId: number) => adminService.listTenantUsers(tenantId))
export const createTenantUser = createAsyncThunk('admin/createTenantUser', ({ tenantId, data }: { tenantId: number; data: { username: string; email: string; password: string; role?: string; is_master_admin?: boolean } }) => adminService.createTenantUser(tenantId, data))
export const updateTenantUser = createAsyncThunk('admin/updateTenantUser', ({ tenantId, userId, data }: { tenantId: number; userId: number; data: { username?: string; email?: string; is_master_admin?: boolean } }) => adminService.updateTenantUser(tenantId, userId, data))
export const setTenantUserRole = createAsyncThunk('admin/setTenantUserRole', ({ tenantId, userId, role }: { tenantId: number; userId: number; role: string }) => adminService.setTenantUserRole(tenantId, userId, role))
export const deactivateTenantUser = createAsyncThunk('admin/deactivateTenantUser', ({ tenantId, userId }: { tenantId: number; userId: number }) => adminService.deactivateTenantUser(tenantId, userId))
export const reactivateTenantUser = createAsyncThunk('admin/reactivateTenantUser', ({ tenantId, userId }: { tenantId: number; userId: number }) => adminService.reactivateTenantUser(tenantId, userId))
export const resetUserPassword = createAsyncThunk('admin/resetUserPassword', ({ tenantId, userId, newPassword }: { tenantId: number; userId: number; newPassword: string }) => adminService.resetUserPassword(tenantId, userId, newPassword))
export const signInAsTenant = createAsyncThunk<
  { access_token: string; token_type: string; target_tenant: TenantResponse },
  number,
  { dispatch: AppDispatch }
>('admin/signInAsTenant', async (tenantId: number, { dispatch }) => {
  const result = await adminService.signInAsTenant(tenantId)
  dispatch(enterImpersonation({ token: result.access_token, tenant: result.target_tenant }))
  return result
})

const adminSlice = createSlice({
  name: 'admin',
  initialState: { tenants: [], tenantUsers: [], loading: false, error: null } as AdminState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchTenants.fulfilled, (state, action) => { state.tenants = action.payload; state.loading = false })
      .addCase(fetchTenants.pending, (state) => { state.loading = true; state.error = null })
      .addCase(fetchTenants.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(createTenant.fulfilled, (state, action) => { state.tenants.push(action.payload); state.loading = false })
      .addCase(createTenant.pending, (state) => { state.loading = true; state.error = null })
      .addCase(createTenant.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(disableTenant.pending, (state) => { state.loading = true; state.error = null })
      .addCase(disableTenant.fulfilled, (state, action) => {
        const idx = state.tenants.findIndex(t => t.id === action.payload.id)
        if (idx !== -1) state.tenants[idx] = action.payload
        state.loading = false
      })
      .addCase(disableTenant.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(fetchTenantUsers.fulfilled, (state, action) => { state.tenantUsers = action.payload; state.loading = false })
      .addCase(fetchTenantUsers.pending, (state) => { state.loading = true; state.error = null })
      .addCase(fetchTenantUsers.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(createTenantUser.pending, (state) => { state.loading = true; state.error = null })
      .addCase(createTenantUser.fulfilled, (state, action) => { state.tenantUsers.push(action.payload); state.loading = false })
      .addCase(createTenantUser.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(updateTenantUser.fulfilled, (state, action) => {
        const idx = state.tenantUsers.findIndex(u => u.id === action.payload.id)
        if (idx !== -1) state.tenantUsers[idx] = action.payload
        state.loading = false
      })
      .addCase(updateTenantUser.pending, (state) => { state.loading = true; state.error = null })
      .addCase(updateTenantUser.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(setTenantUserRole.fulfilled, (state, action) => {
        const idx = state.tenantUsers.findIndex(u => u.id === action.payload.id)
        if (idx !== -1) state.tenantUsers[idx] = action.payload
        state.loading = false
      })
      .addCase(setTenantUserRole.pending, (state) => { state.loading = true; state.error = null })
      .addCase(setTenantUserRole.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(deactivateTenantUser.fulfilled, (state, action) => {
        const idx = state.tenantUsers.findIndex(u => u.id === action.payload.id)
        if (idx !== -1) state.tenantUsers[idx] = action.payload
        state.loading = false
      })
      .addCase(deactivateTenantUser.pending, (state) => { state.loading = true; state.error = null })
      .addCase(deactivateTenantUser.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(reactivateTenantUser.fulfilled, (state, action) => {
        const idx = state.tenantUsers.findIndex(u => u.id === action.payload.id)
        if (idx !== -1) state.tenantUsers[idx] = action.payload
        state.loading = false
      })
      .addCase(reactivateTenantUser.pending, (state) => { state.loading = true; state.error = null })
      .addCase(reactivateTenantUser.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(resetUserPassword.fulfilled, (state) => { state.loading = false })
      .addCase(resetUserPassword.pending, (state) => { state.loading = true; state.error = null })
      .addCase(resetUserPassword.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(signInAsTenant.pending, (state) => { state.loading = true; state.error = null })
      .addCase(signInAsTenant.fulfilled, (state) => { state.loading = false })
      .addCase(signInAsTenant.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
  }
})

export default adminSlice.reducer
