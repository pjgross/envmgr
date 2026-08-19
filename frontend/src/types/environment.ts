import type { DecommissionState } from './decommission';

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
  /** B5 — no deployment or booking for the threshold. Advisory only. */
  idle: boolean;
  /** B5 — the live decommission's computed state, or null if there is none. */
  decommission_state: DecommissionState | null;
  status: EnvironmentStatus;
  tenant_id: number;
  custom_fields: Record<string, unknown> | null;
  operations_group_id: number | null;
  operations_group_name: string | null;
  /** The Welcome Pack's content — read-only here; written only via PATCH /environments/{id}/handover. */
  access_url: string | null;
  connection_notes: string | null;
  support_contact: string | null;
  sla_notes: string | null;
  known_limitations: string | null;
  decommission_notes: string | null;
  /**
   * B2. NULL means "no pattern applies" — it counts as COMPLIANT, never as
   * unknown and never as failing. No policy row, a disabled policy, or a
   * policy with no `name_pattern` all read as null.
   */
  name_compliant?: boolean | null;
  /** Derived on read from the stored verdict, `created_at` and the policy. Advisory: it blocks nothing. */
  quarantined?: boolean;
  compliance_gaps?: string[];
  created_at: string;
  updated_at: string;
}

export interface EnvironmentNamingPolicy {
  is_enabled: boolean;
  name_pattern: string | null;
  name_pattern_example: string | null;
  required_attributes: string[];
  grace_days: number;
  effective_from: string;
}

/**
 * What PUT accepts, which is NOT what GET returns: `effective_from` is the
 * server's to set (it bumps whenever the pattern or the attribute list changes,
 * in either direction), and `EnvironmentNamingPolicyUpdate` declares
 * `extra="forbid"` — so echoing the whole read model back is a 422, not a
 * harmless extra key.
 */
export type EnvironmentNamingPolicyUpdate = Omit<EnvironmentNamingPolicy, 'effective_from'>;

export interface EnvironmentNamingPolicyPreview {
  total_environments: number;
  in_gap: number;
  quarantined_now: number;
  /**
   * Capped server-side at 20. The COUNTS above are exact; this is a sample, and
   * anything rendering it must say so rather than imply it is the whole set.
   */
  sample_names: string[];
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
  operations_group_id?: number | null;
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
  /**
   * `null` clears the group. The backend keys on `model_fields_set`, so an
   * omitted key means "leave alone" — only an explicit null clears it.
   */
  operations_group_id?: number | null;
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
