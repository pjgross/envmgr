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
}

export interface EnvironmentTierCreate {
  name: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
}

export interface EnvironmentTierUpdate {
  name?: string;
  description?: string | null;
  color?: string | null;
  display_order?: number;
  is_active?: boolean;
}
