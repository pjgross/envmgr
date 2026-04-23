export interface LifecycleState {
  key: string;
  label: string;
  is_initial: boolean;
  is_terminal: boolean;
  is_admission_lockdown?: boolean;
}

export interface LifecycleTransition {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

export interface LifecycleFieldPermission {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields?: Record<string, { editable_by: string[] }>;
}

export interface LifecycleDefinition {
  states: LifecycleState[];
  transitions: LifecycleTransition[];
  field_permissions: Record<string, LifecycleFieldPermission>;
  /** Enterprise-only: per-state per-action role lists.
   * Shape: { [stateKey]: { "membership.admit": [...roles], ... } } */
  action_permissions?: Record<string, Record<string, string[]>>;
}

export interface BookingLifecycleTemplate {
  id: number;
  tenant_id: number;
  entity_type: string;
  name: string;
  description: string | null;
  is_default: boolean;
  applies_to_kind?: string | null;
  definition: LifecycleDefinition;
  created_at: string;
  updated_at: string;
}

export interface BookingTypeRecord {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  lifecycle_template_id: number;
  color: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BookingStatusHistory {
  id: number;
  from_state: string | null;
  to_state: string;
  changed_by: number;
  changed_at: string;
  notes: string | null;
}

export interface AllowedTransition {
  from_state: string;
  to_state: string;
  label: string;
}
