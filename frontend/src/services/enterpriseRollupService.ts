import api from './api';
import type {
  SystemRollupRow,
  ScopeRollupItem,
  TimelineRollup,
  MemberRollupRow,
} from '../types/enterpriseReport';

const toRollupSystem = (r: any): SystemRollupRow => ({
  systemId: r.system_id,
  systemName: r.system_name,
  rolesByProject: r.roles_by_project,
});

const toRollupScope = (r: any): ScopeRollupItem => ({
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

const toMember = (r: any): MemberRollupRow => ({
  projectReleaseId: r.project_release_id,
  projectReleaseName: r.project_release_name,
  status: r.status,
  admittedAt: r.admitted_at,
  lateScope: r.late_scope,
});

export const enterpriseRollupService = {
  async systems(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/systems`);
    return (data as any[]).map(toRollupSystem);
  },
  async scope(enterpriseId: number, filters: Record<string, string | number | undefined> = {}) {
    const cleanedParams: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(filters)) {
      if (v !== undefined && v !== '') cleanedParams[k] = v as string | number;
    }
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/scope`, {
      params: cleanedParams,
    });
    return (data as any[]).map(toRollupScope);
  },
  async timeline(enterpriseId: number): Promise<TimelineRollup> {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/timeline`);
    const mapPhase = (p: any) => ({
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
      enterprisePhases: data.enterprise_phases.map(mapPhase),
      childPhasesByRelease: Object.fromEntries(
        Object.entries(data.child_phases_by_release as Record<string, any[]>).map(
          ([k, v]) => [Number(k), v.map(mapPhase)]
        )
      ),
      dependencies: data.dependencies.map((d: any) => ({
        fromReleaseId: d.from_release_id,
        toReleaseId: d.to_release_id,
        alert: d.alert,
      })),
    };
  },
  async members(enterpriseId: number) {
    const { data } = await api.get(`/releases/${enterpriseId}/rollup/members`);
    return (data as any[]).map(toMember);
  },
};
