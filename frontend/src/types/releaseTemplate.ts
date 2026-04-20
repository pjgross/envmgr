export interface ReleaseTemplatePhase {
  name: string;
  order: number;
  default_duration_days: number;
  activities: string[];
}

export interface ReleaseTemplateGate {
  name: string;
  phase_name: string | null;
  acceptance_criteria: string | null;
}

export interface ReleaseTemplateResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  release_type: string;
  default_lifecycle_template_id: number | null;
  phases: ReleaseTemplatePhase[];
  gates: ReleaseTemplateGate[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface ReleaseTemplateCreatePayload {
  name: string;
  description?: string | null;
  release_type: string;
  default_lifecycle_template_id?: number | null;
  phases?: ReleaseTemplatePhase[];
  gates?: ReleaseTemplateGate[];
}

export interface ReleaseTemplateUpdatePayload {
  name?: string;
  description?: string | null;
  release_type?: string;
  default_lifecycle_template_id?: number | null;
  phases?: ReleaseTemplatePhase[];
  gates?: ReleaseTemplateGate[];
}

export interface ReleaseTemplateInstantiatePayload {
  name: string;
  target_date: string;
  description?: string | null;
  custom_fields?: Record<string, unknown> | null;
}
