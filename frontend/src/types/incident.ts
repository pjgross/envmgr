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
  /** The reviews that CITE this incident as evidence. A list, not a single
   *  ref: one incident can be cited by several releases' reviews, and by more
   *  than one finding within one review. */
  pir_citations: IncidentPirCitation[];
}

export interface IncidentPirCitation {
  pir_id: number;
  release_id: number;
  release_name: string;
  pir_status: 'draft' | 'complete';
  finding_id: number;
  finding_title: string;
  root_cause: string | null;
  note: string | null;
  action_count: number;
  /** Why this is on the incident page at all: the reader sees whether the
   *  process fix is still outstanding without opening the release. */
  open_action_count: number;
}

export interface IncidentCreate {
  title: string; description?: string; severity: Severity; detected_at?: string;
  environment_id?: number | null; deployment_id?: number | null;
  release_id?: number | null; fix_release_id?: number | null;
  system_id?: number | null; subsystem_id?: number | null;
  source?: string; external_ref?: string | null; custom_fields?: Record<string, unknown> | null;
}
export type IncidentUpdate = Partial<Omit<IncidentCreate, 'source'>>;
