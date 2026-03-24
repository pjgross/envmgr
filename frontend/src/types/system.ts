export interface SystemResponse {
  id: number;
  name: string;
  description: string | null;
  tenant_id: number;
  github_repository_url: string | null;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SubSystemResponse {
  id: number;
  name: string;
  description: string | null;
  system_id: number;
  tenant_id: number;
  component_type: string;
  technology: string | null;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SystemCreate {
  name: string;
  description?: string;
  github_repository_url?: string;
  custom_fields?: Record<string, unknown>;
}

export interface SystemUpdate {
  name?: string;
  description?: string;
  github_repository_url?: string;
  custom_fields?: Record<string, unknown>;
}

export interface SubSystemCreate {
  name: string;
  description?: string;
  custom_fields?: Record<string, unknown>;
}

export interface SubSystemUpdate {
  name?: string;
  description?: string;
  custom_fields?: Record<string, unknown>;
}
