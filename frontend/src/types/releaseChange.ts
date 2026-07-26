export interface ReleaseChangeResponse {
  id: number;
  tenant_id: number;
  release_id: number | null;
  external_key: string | null;
  title: string;
  description: string | null;
  change_kind: string; // 'story' | 'defect'
  external_status: string | null;
  project_code: string | null;
  project_name: string | null;
  system_id: number | null;
  custom_fields: Record<string, unknown> | null;
  jira_project_config_id: number | null;
  epic_id: number | null;
  source: string; // 'manual' | 'jira'
  move_count: number;
  time_in_current_status_seconds: number | null;
  is_scope_creep?: boolean;
}

export interface ReleaseChangeMovePayload {
  release_id: number | null;
  notes?: string | null;
}

export interface ReleaseChangeReleaseHistoryResponse {
  id: number;
  change_id: number;
  from_release_id: number | null;
  to_release_id: number | null;
  moved_at: string;
  moved_by: number | null;
  notes: string | null;
}

export interface ReleaseChangeStatusHistoryResponse {
  id: number;
  change_id: number;
  from_status: string | null;
  to_status: string | null;
  changed_at: string;
  changed_by: number | null;
  notes: string | null;
}

export interface ReleaseChangeCreatePayload {
  external_key?: string | null;
  title: string;
  description?: string | null;
  change_kind: string;
  external_status?: string | null;
  project_code?: string | null;
  project_name?: string | null;
  system_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ReleaseChangeUpdatePayload {
  external_key?: string | null;
  title?: string;
  description?: string | null;
  external_status?: string | null;
  project_code?: string | null;
  project_name?: string | null;
  system_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ScopeImportRowError {
  row: number;
  field: string;
  message: string;
}

export interface ScopeImportResult {
  created: number;
  updated: number;
  errors: ScopeImportRowError[];
}
