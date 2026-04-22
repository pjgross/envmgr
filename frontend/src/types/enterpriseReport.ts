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
