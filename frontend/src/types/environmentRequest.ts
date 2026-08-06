export type EnvironmentRequestKind = 'access' | 'new_environment';

export interface EnvironmentRequestResponse {
  id: number;
  tenant_id: number;
  kind: EnvironmentRequestKind;
  status: string;
  lifecycle_id: number;
  requested_by: number;
  /** Travels with the row — never resolved against a capped collection. */
  requester_username: string | null;
  justification: string;
  needed_by: string | null;
  environment_id: number | null;
  environment_name: string | null;
  proposed_name: string | null;
  tier_id: number | null;
  tier_name: string | null;
  expires_at: string | null;
  operations_group_id: number | null;
  operations_group_name: string | null;
  created_environment_id: number | null;
  // M4: no custom_fields — the backend no longer accepts or returns it (no
  // tenant can define a vocabulary for this entity's custom fields).
  created_at: string;
  updated_at: string;
}

export interface EnvironmentRequestCreate {
  kind: EnvironmentRequestKind;
  justification: string;
  needed_by?: string | null;
  environment_id?: number | null;
  proposed_name?: string | null;
  tier_id?: number | null;
  expires_at?: string | null;
}

export interface EnvironmentRequestUpdate {
  justification?: string;
  needed_by?: string | null;
  environment_id?: number | null;
  proposed_name?: string | null;
  tier_id?: number | null;
  expires_at?: string | null;
  operations_group_id?: number | null;
}

export interface AllowedTransition {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

export interface WelcomePack {
  environment: Record<string, unknown>;
  access: Record<string, string>;
  support: { sla_notes: string; operations_group: string; operations_group_members: string[] };
  caveats: { known_limitations: string };
  offboarding: { decommission_notes: string };
  context: Record<string, unknown>;
}

export interface EnvironmentHandoverUpdate {
  access_url?: string | null;
  connection_notes?: string | null;
  support_contact?: string | null;
  sla_notes?: string | null;
  known_limitations?: string | null;
  decommission_notes?: string | null;
}
