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
