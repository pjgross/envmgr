import api from './api'
import type { TenantResponse, UserResponse } from '../types'

export const adminService = {
  listTenants: () => api.get<TenantResponse[]>('/admin/tenants').then(r => r.data),
  createTenant: (data: { name: string; slug: string; settings?: Record<string, unknown> }) =>
    api.post<TenantResponse>('/admin/tenants', data).then(r => r.data),
  getTenant: (id: number) => api.get<TenantResponse>(`/admin/tenants/${id}`).then(r => r.data),
  updateTenant: (id: number, data: { name?: string; slug?: string; settings?: Record<string, unknown> }) =>
    api.patch<TenantResponse>(`/admin/tenants/${id}`, data).then(r => r.data),
  disableTenant: (id: number) => api.post<TenantResponse>(`/admin/tenants/${id}/disable`).then(r => r.data),
  listTenantUsers: (tenantId: number) =>
    api.get<UserResponse[]>(`/admin/tenants/${tenantId}/users`).then(r => r.data),
  createTenantUser: (tenantId: number, data: { username: string; email: string; password: string; role?: string; is_master_admin?: boolean }) =>
    api.post<UserResponse>(`/admin/tenants/${tenantId}/users`, data).then(r => r.data),
  updateTenantUser: (tenantId: number, userId: number, data: { username?: string; email?: string; is_master_admin?: boolean }) =>
    api.patch<UserResponse>(`/admin/tenants/${tenantId}/users/${userId}`, data).then(r => r.data),
  setTenantUserRole: (tenantId: number, userId: number, role: string) =>
    api.patch<UserResponse>(`/admin/tenants/${tenantId}/users/${userId}/role`, { role }).then(r => r.data),
  deactivateTenantUser: (tenantId: number, userId: number) =>
    api.post<UserResponse>(`/admin/tenants/${tenantId}/users/${userId}/deactivate`).then(r => r.data),
  reactivateTenantUser: (tenantId: number, userId: number) =>
    api.post<UserResponse>(`/admin/tenants/${tenantId}/users/${userId}/reactivate`).then(r => r.data),
  resetUserPassword: (tenantId: number, userId: number, newPassword: string) =>
    api.post<UserResponse>(`/admin/tenants/${tenantId}/users/${userId}/reset-password`, { new_password: newPassword }).then(r => r.data),
  signInAsTenant: (tenantId: number) =>
    api.post<{ access_token: string; token_type: string; target_tenant: TenantResponse }>(`/admin/tenants/${tenantId}/sign-in-as`).then(r => r.data),
}
