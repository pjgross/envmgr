export interface SystemRollupRow {
  systemId: number;
  systemName: string;
  rolesByProject: Record<string, string[]>;
}

export interface ScopeRollupItem {
  releaseChangeId: number;
  projectReleaseId: number;
  projectReleaseName: string;
  externalKey?: string | null;
  title: string;
  changeKind: string;
  externalStatus?: string | null;
  systemId?: number | null;
  systemName?: string | null;
}

export interface TimelinePhase {
  releaseId: number;
  releaseName: string;
  releaseKind: string;
  phaseId?: number | null;
  phaseName: string;
  startDate?: string | null;
  endDate?: string | null;
  status?: string | null;
}

export interface TimelineDependencyEdge {
  fromReleaseId: number;
  toReleaseId: number;
  fromReleaseName?: string | null;
  toReleaseName?: string | null;
  alert?: string | null;
}

export interface TimelineRollup {
  enterprisePhases: TimelinePhase[];
  childPhasesByRelease: Record<number, TimelinePhase[]>;
  dependencies: TimelineDependencyEdge[];
}

export interface MemberRollupRow {
  projectReleaseId: number;
  projectReleaseName: string;
  status: string;
  admittedAt?: string | null;
  lateScope: boolean;
}

export interface EnterpriseReportEvent {
  releaseId: number;
  releaseName: string;
  occurredAt: string;
  eventType: string;
  description?: string | null;
}

export interface EnterpriseReport {
  enterpriseId: number;
  name: string;
  status: string;
  targetDate?: string | null;
  actualDate?: string | null;
  description?: string | null;
  members: MemberRollupRow[];
  systems: SystemRollupRow[];
  scopeByProject: Record<string, ScopeRollupItem[]>;
  events: EnterpriseReportEvent[];
  dependencies: TimelineDependencyEdge[];
  generatedAt: string;
  generatedBy: string;
}

// ── Wire shapes ───────────────────────────────────────────────────────────
// The backend serialises snake_case; these describe the raw payloads so the
// service-layer mappers have a typed input instead of `any`.

export interface ApiSystemRollupRow {
  system_id: number;
  system_name: string;
  roles_by_project: Record<string, string[]>;
}

export interface ApiScopeRollupItem {
  release_change_id: number;
  project_release_id: number;
  project_release_name: string;
  external_key?: string | null;
  title: string;
  change_kind: string;
  external_status?: string | null;
  system_id?: number | null;
  system_name?: string | null;
}

export interface ApiTimelinePhase {
  release_id: number;
  release_name: string;
  release_kind: string;
  phase_id?: number | null;
  phase_name: string;
  start_date?: string | null;
  end_date?: string | null;
  status?: string | null;
}

export interface ApiTimelineDependencyEdge {
  from_release_id: number;
  to_release_id: number;
  from_release_name?: string | null;
  to_release_name?: string | null;
  alert?: string | null;
}

export interface ApiTimelineRollup {
  enterprise_phases: ApiTimelinePhase[];
  child_phases_by_release: Record<string, ApiTimelinePhase[]>;
  dependencies: ApiTimelineDependencyEdge[];
}

export interface ApiMemberRollupRow {
  project_release_id: number;
  project_release_name: string;
  status: string;
  admitted_at?: string | null;
  late_scope: boolean;
}

export interface ApiEnterpriseReportEvent {
  release_id: number;
  release_name: string;
  occurred_at: string;
  event_type: string;
  description?: string | null;
}

export interface ApiEnterpriseReport {
  enterprise_id: number;
  name: string;
  status: string;
  target_date?: string | null;
  actual_date?: string | null;
  description?: string | null;
  members: ApiMemberRollupRow[];
  systems: ApiSystemRollupRow[];
  scope_by_project: Record<string, ApiScopeRollupItem[]>;
  events: ApiEnterpriseReportEvent[];
  dependencies: ApiTimelineDependencyEdge[];
  generated_at: string;
  generated_by: string;
}
