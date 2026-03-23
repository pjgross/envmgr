import api from './api'
import type { TenantResponse, UserResponse } from '../types'

export const tenantAdminService = {
  getSettings: () => api.get<TenantResponse>('/tenant/settings').then(r => r.data),
  updateSettings: (settings: Record<string, unknown>) =>
    api.patch<TenantResponse>('/tenant/settings', { settings }).then(r => r.data),
  listUsers: () => api.get<UserResponse[]>('/tenant/users').then(r => r.data),
  createUser: (data: { username: string; email: string; password: string; role?: string }) =>
    api.post<UserResponse>('/tenant/users', data).then(r => r.data),
  getUser: (id: number) => api.get<UserResponse>(`/tenant/users/${id}`).then(r => r.data),
  updateUser: (id: number, data: { username?: string; email?: string }) =>
    api.patch<UserResponse>(`/tenant/users/${id}`, data).then(r => r.data),
  setUserRole: (id: number, role: string) =>
    api.patch<UserResponse>(`/tenant/users/${id}/role`, { role }).then(r => r.data),
  deactivateUser: (id: number) =>
    api.post<UserResponse>(`/tenant/users/${id}/deactivate`).then(r => r.data),
}
