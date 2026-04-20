export interface ReleaseChangeResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  external_key: string | null;
  title: string;
  description: string | null;
  change_kind: string; // 'story' | 'defect'
  external_status: string | null;
  system_id: number | null;
  custom_fields: Record<string, unknown> | null;
  jira_project_config_id: number | null;
  epic_id: number | null;
  source: string; // 'manual' | 'jira'
}

export interface ReleaseChangeCreatePayload {
  external_key?: string | null;
  title: string;
  description?: string | null;
  change_kind: string;
  external_status?: string | null;
  system_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ReleaseChangeUpdatePayload {
  external_key?: string | null;
  title?: string;
  description?: string | null;
  external_status?: string | null;
  system_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}
