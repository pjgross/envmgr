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
  /**
   * The gate type (Phase 9 C2) this gate skeleton materialises onto a
   * created release's gate. Optional — a gate with no type is legitimate
   * and back-compat: a template saved before this field existed has no
   * key for it at all, and setGates(detail.gates) preserves that (the
   * value reads as `undefined`, treated identically to `null` everywhere
   * this is read). See backend/app/api/v1/schemas/release_template.py.
   */
  gate_type_id?: number | null;
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
