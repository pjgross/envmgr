/**
 * Phase 9 C4 — rollback governance: per-component rollback plans, per-system
 * rehearsals, per-release rollback authorisations, and the per-tenant policy
 * that decides whether missing plans/rehearsals are warnings or blockers in
 * the readiness verdict.
 *
 * Mirrors backend/app/api/v1/schemas/rollback.py exactly.
 *
 * C4 RECORDS ROLLBACK GOVERNANCE; IT NEVER REFUSES A ROLLBACK. The
 * authorisation endpoints never inspect plan or rehearsal state — recording a
 * rollback that had no plan at all is exactly the case worth keeping an audit
 * trail of. See backend/tests/test_c4_records_never_refuses.py.
 */

export type Reversibility = 'reversible' | 'lossy' | 'irreversible';
export type RehearsalOutcome = 'passed' | 'failed' | 'partial';
export type RehearsalState = 'current' | 'stale';

export interface RollbackPlanCreate {
  system_id: number;
  steps: string;
  reversibility: Reversibility;
  estimated_minutes?: number | null;
  notes?: string | null;
}

export interface RollbackPlanResponse {
  id: number;
  release_id: number;
  system_id: number;
  system_name: string | null;
  steps: string;
  reversibility: string;
  estimated_minutes: number | null;
  notes: string | null;
  agreed_by_user_id: number | null;
  agreed_by_username: string | null;
  agreed_at: string | null;
}

export interface RehearsalCreate {
  rehearsed_at: string;
  outcome: RehearsalOutcome;
  notes?: string | null;
}

export interface RehearsalResponse {
  id: number;
  system_id: number;
  rehearsed_at: string;
  rehearsed_by_user_id: number;
  rehearsed_by_username: string | null;
  outcome: string;
  notes: string | null;
  // COMPUTED on every read — see rollback_rehearsal_service.rehearsal_state.
  // A `failed` outcome can still be 'current': the freshness clock and the
  // pass/fail verdict are two different questions, and a panel must render
  // both honestly rather than conflating "recent" with "passed".
  state: RehearsalState;
}

export interface RollbackAuthorisationCreate {
  // Caller-supplied and may be in the past — a rollback that already
  // happened is recorded as-is, never stamped with "now".
  decided_at: string;
  trigger: string;
  rationale: string;
  system_ids: number[];
}

export interface RollbackAuthorisationResponse {
  id: number;
  release_id: number;
  decided_by_user_id: number;
  decided_by_username: string | null;
  decided_at: string;
  trigger: string;
  rationale: string;
  system_ids: number[];
  system_names: string[];
}

export interface RollbackPolicy {
  require_rollback_plan: boolean;
  require_current_rehearsal: boolean;
  rehearsal_validity_days: number;
}

export interface RollbackPolicyUpdate {
  // All optional — the backend keys on "not None means set", so an omitted
  // key must leave that setting alone rather than resetting it.
  require_rollback_plan?: boolean;
  require_current_rehearsal?: boolean;
  rehearsal_validity_days?: number;
}
