// frontend/src/types/apiKey.ts
export interface ApiKey {
  id: number;
  name: string;
  scopes: string[];
  created_by: number;
  created_by_username: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  expires_at?: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}
