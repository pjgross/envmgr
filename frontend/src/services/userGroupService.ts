import api from './api';
import type {
  UserGroupCreate,
  UserGroupMemberResponse,
  UserGroupResponse,
  UserGroupUpdate,
} from '../types/userGroup';
import type { Paged } from '../types/pagination';

export const userGroupService = {
  listGroups: (params?: {
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
    search?: string;
  }): Promise<Paged<UserGroupResponse>> =>
    api.get<UserGroupResponse[]>('/tenant/groups', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createGroup: (data: UserGroupCreate): Promise<UserGroupResponse> =>
    api.post('/tenant/groups', data).then((r) => r.data),

  updateGroup: (id: number, data: UserGroupUpdate): Promise<UserGroupResponse> =>
    api.patch(`/tenant/groups/${id}`, data).then((r) => r.data),

  deleteGroup: (id: number): Promise<void> =>
    api.delete(`/tenant/groups/${id}`).then((r) => r.data),

  listMembers: (
    groupId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<UserGroupMemberResponse>> =>
    api
      .get<UserGroupMemberResponse[]>(`/tenant/groups/${groupId}/members`, { params })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  addMember: (groupId: number, userId: number): Promise<UserGroupMemberResponse> =>
    api.post(`/tenant/groups/${groupId}/members`, { user_id: userId }).then((r) => r.data),

  removeMember: (groupId: number, userId: number): Promise<void> =>
    api.delete(`/tenant/groups/${groupId}/members/${userId}`).then((r) => r.data),
};
