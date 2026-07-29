export type Severity = 'P1' | 'P2' | 'P3' | 'P4';

export interface ReleaseSummary { id: number; name: string; target_date: string | null; status: string; }
export interface ReleaseChangeRow { id: number; title: string; epic_id: number | null; }
export interface TransitionOption { to_state: string; label: string; }
export interface StatusHistoryRow { from_state: string | null; to_state: string; changed_by: number | null; changed_at: string; }

export interface IncidentListRow {
  id: number; title: string; severity: Severity; status: string;
  detected_at: string; resolved_at: string | null;
  system_id: number | null; system_name: string | null;
  environment_id: number | null; environment_name: string | null;
  release_id: number | null; release_name: string | null;
  fix_release: ReleaseSummary | null;
  pir_status: 'complete' | 'draft' | 'none';
}

export interface IncidentDetail {
  id: number; title: string; description: string | null; severity: Severity; status: string;
  detected_at: string; resolved_at: string | null; source: string; external_ref: string | null;
  environment_id: number | null; environment_name: string | null; deployment_id: number | null;
  release_id: number | null; release: ReleaseSummary | null;
  fix_release_id: number | null; fix_release: ReleaseSummary | null;
  fix_release_changes_by_epic: Record<string, ReleaseChangeRow[]>;
  system_id: number | null; system_name: string | null;
  subsystem_id: number | null; subsystem_name: string | null;
  custom_fields: Record<string, unknown> | null;
  allowed_transitions: TransitionOption[];
  status_history: StatusHistoryRow[];
  pir: { release_id: number; status: string; root_cause: string | null; action_plan: string | null; summary: string | null } | null;
}

export interface IncidentCreate {
  title: string; description?: string; severity: Severity; detected_at?: string;
  environment_id?: number | null; deployment_id?: number | null;
  release_id?: number | null; fix_release_id?: number | null;
  system_id?: number | null; subsystem_id?: number | null;
  source?: string; external_ref?: string | null; custom_fields?: Record<string, unknown> | null;
}
export type IncidentUpdate = Partial<Omit<IncidentCreate, 'source'>>;
