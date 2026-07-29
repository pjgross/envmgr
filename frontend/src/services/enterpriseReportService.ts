import api from './api';
import type { ApiEnterpriseReport, EnterpriseReport } from '../types/enterpriseReport';

export const enterpriseReportService = {
  async generate(enterpriseId: number): Promise<EnterpriseReport> {
    const data = (await api.get(`/releases/${enterpriseId}/report`)).data as ApiEnterpriseReport;
    return {
      enterpriseId: data.enterprise_id,
      name: data.name,
      status: data.status,
      targetDate: data.target_date,
      actualDate: data.actual_date,
      description: data.description,
      members: data.members.map((m) => ({
        projectReleaseId: m.project_release_id,
        projectReleaseName: m.project_release_name,
        status: m.status,
        admittedAt: m.admitted_at,
        lateScope: m.late_scope,
      })),
      systems: data.systems.map((s) => ({
        systemId: s.system_id,
        systemName: s.system_name,
        rolesByProject: s.roles_by_project,
      })),
      scopeByProject: Object.fromEntries(
        Object.entries(data.scope_by_project).map(
          ([k, v]) => [k, v.map((it) => ({
            releaseChangeId: it.release_change_id,
            projectReleaseId: it.project_release_id,
            projectReleaseName: it.project_release_name,
            externalKey: it.external_key,
            title: it.title,
            changeKind: it.change_kind,
            externalStatus: it.external_status,
            systemId: it.system_id,
            systemName: it.system_name,
          }))]
        )
      ),
      events: data.events.map((e) => ({
        releaseId: e.release_id,
        releaseName: e.release_name,
        occurredAt: e.occurred_at,
        eventType: e.event_type,
        description: e.description,
      })),
      dependencies: data.dependencies.map((d) => ({
        fromReleaseId: d.from_release_id,
        toReleaseId: d.to_release_id,
        fromReleaseName: d.from_release_name,
        toReleaseName: d.to_release_name,
        alert: d.alert,
      })),
      generatedAt: data.generated_at,
      generatedBy: data.generated_by,
    };
  },
};
