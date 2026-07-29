import api from './api';
import type {
  ReleaseMembership,
  MembershipCreatePayload,
  MembershipRejectPayload,
  MembershipRemovePayload,
  ApiReleaseMembership,
  ApiProjectMembership,
} from '../types/enterpriseMembership';

const toCamel = (m: ApiReleaseMembership): ReleaseMembership => ({
  id: m.id,
  tenantId: m.tenant_id,
  enterpriseReleaseId: m.enterprise_release_id,
  projectReleaseId: m.project_release_id,
  projectReleaseName: m.project_release_name,
  projectReleaseStatus: m.project_release_status,
  enterpriseReleaseName: m.enterprise_release_name,
  state: m.state,
  requestedBy: m.requested_by,
  requestedByUsername: m.requested_by_username,
  requestedAt: m.requested_at,
  decidedBy: m.decided_by,
  decidedByUsername: m.decided_by_username,
  decidedAt: m.decided_at,
  removedBy: m.removed_by,
  removedByUsername: m.removed_by_username,
  removedAt: m.removed_at,
  removalReason: m.removal_reason,
  lateScope: m.late_scope,
  notes: m.notes,
});

export const enterpriseMembershipService = {
  async request(enterpriseId: number, payload: MembershipCreatePayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships`, payload
    );
    return toCamel(data);
  },
  async list(enterpriseId: number, states?: string[]) {
    const { data } = await api.get(`/releases/${enterpriseId}/memberships`, {
      params: states ? { states: states.join(',') } : undefined,
    });
    return (data as ApiReleaseMembership[]).map(toCamel);
  },
  async accept(enterpriseId: number, membershipId: number) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/accept`
    );
    return toCamel(data);
  },
  async reject(enterpriseId: number, membershipId: number, p: MembershipRejectPayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/reject`, p
    );
    return toCamel(data);
  },
  async withdraw(enterpriseId: number, membershipId: number) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/withdraw`
    );
    return toCamel(data);
  },
  async remove(enterpriseId: number, membershipId: number, p: MembershipRemovePayload) {
    const { data } = await api.post(
      `/releases/${enterpriseId}/memberships/${membershipId}/remove`, p
    );
    return toCamel(data);
  },
  async getProjectMembership(projectReleaseId: number) {
    const data = (await api.get(`/releases/${projectReleaseId}/membership`))
      .data as ApiProjectMembership;
    return {
      current: data.current ? toCamel(data.current) : null,
      history: (data.history ?? []).map(toCamel),
    };
  },
};
