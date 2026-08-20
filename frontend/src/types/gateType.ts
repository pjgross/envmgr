/**
 * Tenant-configurable release-gate vocabulary (Phase 9 C2). A GateType names a
 * kind of gate — Functional, Security, Business sign-off, ... — and carries
 * the failure behaviour, expected evidence and deployment-link requirement a
 * release gate materialised from it should inherit.
 *
 * `failure_behaviour` is deliberately never rendered as a plain "Blocks" —
 * C2 ADVISES, IT NEVER BLOCKS. No gate refuses a deployment or a release
 * transition; the value only changes how the gate reads in the readiness
 * verdict (a blocker vs. an advisory warning vs. something that can be
 * accepted with a recorded exception). See GATE_FAILURE_BEHAVIOUR_LABELS in
 * GateTypesPanel.tsx for the exact wording.
 */
export type GateFailureBehaviour = 'block' | 'warn' | 'accept_with_exception';

export interface GateTypeResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  /** The standard gate category this maps onto, or null for a tenant-specific one. */
  category: string | null;
  failure_behaviour: GateFailureBehaviour;
  expected_evidence: string[];
  requires_deployment_link: boolean;
  display_order: number;
  is_active: boolean;
}

export interface GateTypeCreate {
  name: string;
  description?: string | null;
  category?: string | null;
  failure_behaviour?: GateFailureBehaviour;
  expected_evidence?: string[];
  requires_deployment_link?: boolean;
  display_order?: number;
  is_active?: boolean;
}

export interface GateTypeUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  failure_behaviour?: GateFailureBehaviour;
  expected_evidence?: string[];
  requires_deployment_link?: boolean;
  display_order?: number;
  is_active?: boolean;
}
