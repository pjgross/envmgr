import api from './api';
import type {
  EnvironmentGroupCreate,
  EnvironmentGroupResponse,
  EnvironmentGroupUpdate,
  MemberCreate,
  MemberResponse,
} from '../types/environmentGroup';
import type { BookingResponse } from '../types/booking';
import type { AllowedTransition } from '../types/bookingLifecycle';
import type { Paged } from '../types/pagination';

export const environmentGroupService = {
  listGroups: (params?: {
    search?: string;
    is_active?: boolean;
    limit?: number;
    offset?: number;
    sort_by?: 'name' | 'created_at';
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<EnvironmentGroupResponse>> =>
    api.get<EnvironmentGroupResponse[]>('/environment-groups', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  getGroup: (id: number): Promise<EnvironmentGroupResponse> =>
    api.get(`/environment-groups/${id}`).then((r) => r.data),

  createGroup: (data: EnvironmentGroupCreate): Promise<EnvironmentGroupResponse> =>
    api.post('/environment-groups', data).then((r) => r.data),

  updateGroup: (id: number, data: EnvironmentGroupUpdate): Promise<EnvironmentGroupResponse> =>
    api.patch(`/environment-groups/${id}`, data).then((r) => r.data),

  deleteGroup: (id: number): Promise<void> =>
    api.delete(`/environment-groups/${id}`).then((r) => r.data),

  listMembers: (
    groupId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<MemberResponse>> =>
    api
      .get<MemberResponse[]>(`/environment-groups/${groupId}/members`, { params })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  listGroupsForEnvironment: (
    environmentId: number,
    params?: { limit?: number; offset?: number }
  ): Promise<Paged<MemberResponse>> =>
    api
      .get<MemberResponse[]>(`/environments/${environmentId}/groups`, { params })
      .then((r) => ({
        rows: r.data,
        total: Number(r.headers['x-total-count'] ?? r.data.length),
      })),

  addMember: (groupId: number, data: MemberCreate): Promise<MemberResponse> =>
    api.post(`/environment-groups/${groupId}/members`, data).then((r) => r.data),

  removeMember: (groupId: number, memberId: number): Promise<void> =>
    api.delete(`/environment-groups/${groupId}/members/${memberId}`).then((r) => r.data),

  transitionGroup: (
    requestId: number,
    groupId: number,
    data: { to_state: string; notes?: string }
  ): Promise<BookingResponse[]> =>
    api
      .post(`/booking-requests/${requestId}/groups/${groupId}/transition`, data)
      .then((r) => r.data),

  groupAllowedTransitions: (requestId: number, groupId: number): Promise<AllowedTransition[]> =>
    api
      .get(`/booking-requests/${requestId}/groups/${groupId}/allowed-transitions`)
      .then((r) => r.data),
};
