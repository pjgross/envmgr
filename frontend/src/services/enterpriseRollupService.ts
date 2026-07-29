import api from './api';
import type {
  SystemRollupRow,
  ScopeRollupItem,
  TimelinePhase,
  TimelineRollup,
  MemberRollupRow,
  ApiSystemRollupRow,
  ApiScopeRollupItem,
  ApiTimelinePhase,
  ApiTimelineRollup,
  ApiMemberRollupRow,
} from '../types/enterpriseReport';

const toRollupSystem = (r: ApiSystemRollupRow): SystemRollupRow => ({
  systemId: r.system_id,
  systemName: r.system_name,
  rolesByProject: r.roles_by_project,
});

const toRollupScope = (r: ApiScopeRollupItem): ScopeRollupItem => ({
  releaseChangeId: r.release_change_id,
  projectReleaseId: r.project_release_id,
  projectReleaseName: r.project_release_name,
  externalKey: r.external_key,
  title: r.title,
  changeKind: r.change_kind,
  externalStatus: r.external_status,
  systemId: r.system_id,
  systemName: r.system_name,
});

const toMember = (r: ApiMemberRollupRow): MemberRollupRow => ({
  projectReleaseId: r.project_release_id,
  projectReleaseName: r.project_release_name,
  status: r.status,
  admittedAt: r.admitted_at,
  lateScope: r.late_scope,
});

export const enterpriseRollupService = {
  async systems(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/systems`);
    return (data as ApiSystemRollupRow[]).map(toRollupSystem);
  },
  async scope(enterpriseId: number, filters: Record<string, string | number | undefined> = {}) {
    const cleanedParams: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== '') cleanedParams[k] = v as string | number;
    }
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/scope`, {
      params: cleanedParams,
    });
    return (data as ApiScopeRollupItem[]).map(toRollupScope);
  },
  async timeline(enterpriseId: number): Promise<TimelineRollup> {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/timeline`);
    const payload = data as ApiTimelineRollup;
    const mapPhase = (p: ApiTimelinePhase): TimelinePhase => ({
      releaseId: p.release_id,
      releaseName: p.release_name,
      releaseKind: p.release_kind,
      phaseId: p.phase_id,
      phaseName: p.phase_name,
      startDate: p.start_date,
      endDate: p.end_date,
      status: p.status,
    });
    return {
      enterprisePhases: payload.enterprise_phases.map(mapPhase),
      childPhasesByRelease: Object.fromEntries(
        Object.entries(payload.child_phases_by_release).map(
          ([k, v]) => [Number(k), v.map(mapPhase)]
        )
      ),
      dependencies: payload.dependencies.map((d) => ({
        fromReleaseId: d.from_release_id,
        toReleaseId: d.to_release_id,
        fromReleaseName: d.from_release_name,
        toReleaseName: d.to_release_name,
        alert: d.alert,
      })),
    };
  },
  async members(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/members`);
    return (data as ApiMemberRollupRow[]).map(toMember);
  },
};
