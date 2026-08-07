export interface EnvironmentGroupResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  member_count: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface EnvironmentGroupCreate {
  name: string;
  description?: string | null;
  is_active?: boolean;
}

export interface EnvironmentGroupUpdate {
  name?: string;
  description?: string | null;
  is_active?: boolean;
}

export interface MemberCreate {
  environment_id: number;
}

export interface MemberResponse {
  id: number;
  tenant_id: number;
  group_id: number;
  group_name: string;
  environment_id: number;
  environment_name: string;
  created_at: string;
}
