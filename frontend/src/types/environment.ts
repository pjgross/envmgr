export type EnvironmentStatus = 'active' | 'inactive' | 'maintenance' | 'decommissioned';

export interface EnvironmentResponse {
  id: number;
  name: string;
  description: string | null;
  tier_id: number;
  tier_name: string;
  tier_color: string | null;
  owner_user_id: number | null;
  /**
   * The owner's display name, travelling with the row rather than being
   * resolved in the browser against a separately-fetched (and capped) user
   * collection — see docs/pagination.md.
   */
  owner_username: string | null;
  /** Null means "no expiry planned" — a legitimate state, not a missing value. */
  expires_at: string | null;
  reserved_now: boolean;
  status: EnvironmentStatus;
  tenant_id: number;
  custom_fields: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface SystemSummary {
  id: number;
  name: string;
  description: string | null;
}

export interface EnvironmentSystemResponse {
  id: number;
  environment_id: number;
  system_id: number;
  system: {
    id: number;
    name: string;
    description: string | null;
    github_repository_url: string | null;
  };
}

export interface EnvironmentSystemsResponse {
  systems: EnvironmentSystemResponse[];
  missing_systems: SystemSummary[];
}

export interface EnvironmentCreate {
  name: string;
  description?: string;
  tier_id: number;
  owner_user_id: number;
  /** Required on create; `PATCH` may clear it later (see EnvironmentUpdate). */
  expires_at: string;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentUpdate {
  name?: string;
  description?: string;
  tier_id?: number;
  owner_user_id?: number;
  /**
   * `null` clears the expiry — "no expiry planned", which the backend treats
   * as a legitimate state and deliberately excludes from its compliance rule.
   * Omit the key to leave the stored value untouched.
   */
  expires_at?: string | null;
  status?: EnvironmentStatus;
  custom_fields?: Record<string, unknown>;
}

export interface EnvironmentSystemCreate {
  system_id: number;
}

export interface EnvironmentSystemUpdate {
  // reserved for future fields
}

export interface VersionSummary {
  build_id: string;
  version_label: string;
  installed_at: string;
}

export interface EnvironmentSubsystemResponse {
  id: number;
  environment_id: number;
  subsystem_id: number;
  subsystem_name: string;
  component_type: string;
  component_type_definition_id: number | null;
  component_type_definition_name: string | null;
  technology: string | null;
  system_id: number;
  system_name: string;
  is_mocked: boolean;
  mock_notes: string | null;
  custom_fields: Record<string, unknown> | null;
  latest_version: VersionSummary | null;
}

export interface EnvironmentSubsystemUpdate {
  is_mocked?: boolean;
  mock_notes?: string | null;
  component_type_definition_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface EnvSubsystemHostRef {
  infrastructure_component_id: number;
  name: string;
  component_type: string;
  role: string | null;
}

export interface EnvSubsystemNode {
  id: number;
  name: string;
  component_type: string;
  technology: string | null;
  system_id: number;
  is_mocked: boolean;
  hosts: EnvSubsystemHostRef[]; // [] for outside subsystems
}

import type { ComponentDependencyResponse } from './dependency';

export interface EnvironmentTopologyData {
  environment_id: number;
  subsystems: EnvSubsystemNode[];
  dependencies: ComponentDependencyResponse[];
  system_names: Record<string, string>;
  outside_subsystems: EnvSubsystemNode[];
  outside_dependencies: ComponentDependencyResponse[];
}

// Alias for use in components (e.g., EnvironmentPicker)
export type Environment = EnvironmentResponse;
