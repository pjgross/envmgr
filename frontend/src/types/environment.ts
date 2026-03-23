export type EnvironmentStatus = 'active' | 'inactive' | 'maintenance' | 'decommissioned';
export type EnvironmentSystemStatus = 'active' | 'inactive' | 'mock';

export interface EnvironmentResponse {
  id: number;
  name: string;
  description: string | null;
  environment_type: string;
  status: EnvironmentStatus;
  tenant_id: number;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentSystemResponse {
  id: number;
  environment_id: number;
  system_id: number;
  status: EnvironmentSystemStatus;
  mock_notes: string | null;
  system: {
    id: number;
    name: string;
    description: string | null;
    github_repository_url: string | null;
  };
}

export interface EnvironmentCreate {
  name: string;
  description?: string;
  environment_type: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentUpdate {
  name?: string;
  description?: string;
  environment_type?: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentSystemCreate {
  system_id: number;
  status?: EnvironmentSystemStatus;
  mock_notes?: string;
}

export interface EnvironmentSystemUpdate {
  status?: EnvironmentSystemStatus;
  mock_notes?: string;
}
