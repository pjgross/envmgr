export interface ProjectResponse {
  id: number;
  tenant_id: number;
  name: string;
  code: string | null;
  description: string | null;
  team_group_id: number | null;
  team_group_name: string | null;
  environment_count: number;
  is_active: boolean;
  // A4's contention priority. LOWER WINS; null means unranked, a real state,
  // not "not yet loaded" — REQUIRED because the backend's ProjectResponse
  // gives it no Pydantic default either.
  priority_rank: number | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  code?: string | null;
  description?: string | null;
  team_group_id?: number | null;
  is_active?: boolean;
}

export interface ProjectUpdate {
  name?: string;
  code?: string | null;
  description?: string | null;
  team_group_id?: number | null;
  is_active?: boolean;
  // `number | null`, key omitted to mean "leave alone" — the backend keys on
  // model_fields_set, so only an explicit null clears the rank, the same
  // contract `team_group_id` already has. Not in Task 5's own file list but
  // added here because Task 6 (the project admin rank field) modifies
  // ProjectDetail.tsx, not this file, and has nothing else to add it to.
  priority_rank?: number | null;
}

export interface UsageAgreementResponse {
  id: number;
  tenant_id: number;
  project_id: number;
  project_name: string;
  environment_id: number;
  environment_name: string;
  starts_at: string | null;
  ends_at: string | null;
  notes: string | null;
  created_at: string;
}

export interface UsageAgreementCreate {
  environment_id: number;
  starts_at?: string | null;
  ends_at?: string | null;
  notes?: string | null;
}
