// frontend/src/types/build.ts
export interface PipelineStep {
  name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Build {
  id: number;
  tenant_id: number;
  subsystem_id: number;
  release_id: number | null;
  git_sha: string;
  git_branch: string | null;
  build_number: string | null;
  commit_timestamp: string;
  build_started_at: string | null;
  build_finished_at: string | null;
  jira_tickets: string[];
  pipeline_steps: PipelineStep[];
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BuildFilters {
  subsystem_id?: number;
  release_id?: number;
  branch?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}
