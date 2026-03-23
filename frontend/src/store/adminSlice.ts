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
export const createTenantUser = createAsyncThunk('admin/createTenantUser', ({ tenantId, data }: { tenantId: number; data: { username: string; email: string; password: string; role?: string } }) => adminService.createTenantUser(tenantId, data))
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
      .addCase(disableTenant.fulfilled, (state, action) => {
        const idx = state.tenants.findIndex(t => t.id === action.payload.id)
        if (idx !== -1) state.tenants[idx] = action.payload
        state.loading = false
      })
      .addCase(fetchTenantUsers.fulfilled, (state, action) => { state.tenantUsers = action.payload; state.loading = false })
      .addCase(fetchTenantUsers.pending, (state) => { state.loading = true; state.error = null })
      .addCase(fetchTenantUsers.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
      .addCase(createTenantUser.fulfilled, (state, action) => { state.tenantUsers.push(action.payload); state.loading = false })
      .addCase(signInAsTenant.pending, (state) => { state.loading = true; state.error = null })
      .addCase(signInAsTenant.fulfilled, (state) => { state.loading = false })
      .addCase(signInAsTenant.rejected, (state, action) => { state.loading = false; state.error = action.error.message ?? 'Failed' })
  }
})

export default adminSlice.reducer
