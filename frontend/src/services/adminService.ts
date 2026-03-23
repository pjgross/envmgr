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
  createTenantUser: (tenantId: number, data: { username: string; email: string; password: string; role?: string }) =>
    api.post<UserResponse>(`/admin/tenants/${tenantId}/users`, data).then(r => r.data),
  signInAsTenant: (tenantId: number) =>
    api.post<{ access_token: string; token_type: string; target_tenant: TenantResponse }>(`/admin/tenants/${tenantId}/sign-in-as`).then(r => r.data),
}
