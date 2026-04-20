export interface ReleaseEventTypeResponse {
  id: number;
  tenant_id: number;
  name: string;
  display_color: string | null;
  is_system: boolean;
}

export interface ReleaseEventTypeCreatePayload {
  name: string;
  display_color?: string | null;
}

export interface ReleaseEventTypeUpdatePayload {
  name?: string;
  display_color?: string | null;
}

export interface ReleaseEventResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  event_type_id: number;
  description: string;
  occurred_at: string;
  recorded_by: number;
}

export interface ReleaseEventCreatePayload {
  event_type_id: number;
  description: string;
  occurred_at?: string | null;
}
