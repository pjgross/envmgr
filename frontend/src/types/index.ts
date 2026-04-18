export interface TenantResponse {
  id: number;
  name: string;
  slug: string;
  settings: Record<string, unknown> | null;
  is_active: boolean;
  created_at: string;
}

export interface UserResponse {
  id: number;
  username: string;
  email: string;
  role: string;
  tenant_id: number;
  is_active: boolean;
  is_master_admin: boolean;
  created_at: string;
  notification_preferences: Record<string, unknown> | null;
}
