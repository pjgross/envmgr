export interface EnvironmentTierResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  /** The standard tier this maps onto, or null for a tenant-specific one. */
  category: string | null;
  color: string | null;
  display_order: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  /**
   * B5 — per-tier idle override, in days. NULL means "use the tenant's
   * environment_lifecycle_policy.idle_threshold_days" — a legitimate state,
   * not a missing value. A form must render this BLANK when null, never
   * pre-filled with the tenant default: pre-filling it turns every save into
   * an explicit override nobody asked for, silently detaching the tier from
   * future tenant-default changes.
   */
  idle_threshold_days: number | null;
}

export interface EnvironmentTierCreate {
  name: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
  idle_threshold_days?: number | null;
}

export interface EnvironmentTierUpdate {
  name?: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
  /**
   * Explicitly OMITTED vs explicitly NULL both matter here (the backend
   * reads `model_fields_set`): omit the key to leave the override alone,
   * send `null` to clear it back to "use the tenant default". Always send
   * the key when this form field is part of the draft, or a clear silently
   * becomes a no-op.
   */
  idle_threshold_days?: number | null;
}
