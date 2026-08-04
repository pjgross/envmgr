export interface UserGroupResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  /** Computed in SQL, so not sortable server-side — the grid column sets sortable: false. */
  member_count: number;
  environment_count: number;
  created_at: string;
  updated_at: string;
}

export interface UserGroupCreate {
  name: string;
  description?: string | null;
}

export interface UserGroupUpdate {
  name?: string;
  description?: string | null;
}

export interface UserGroupMemberResponse {
  id: number;
  user_id: number;
  /** Travels with the row — never resolved against the capped users list. */
  username: string;
  group_id: number;
  created_at: string;
}
