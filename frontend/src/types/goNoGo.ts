/**
 * Phase 9 C3 — Go/No-Go decision records.
 *
 * Mirrors `backend/app/api/v1/schemas/go_no_go.py` exactly.
 *
 * C3 RECORDS A DECISION A HUMAN TOOK; IT REFUSES NOTHING beyond input
 * validation. Recording a decision does not gate a release transition, a
 * deployment or `can-deploy` — see backend/tests/test_c3_*.py. The readiness
 * snapshot (`snapshot_*` below) is captured SERVER-SIDE by
 * `go_no_go_service.record_decision` calling `release_readiness_service.
 * evaluate`; `GoNoGoDecisionCreate` deliberately carries no snapshot fields —
 * a client-supplied snapshot would be a client-supplied audit record.
 */

export type GoNoGoOutcome = 'go' | 'conditional_go' | 'no_go';

export interface GoNoGoSignoffCreate {
  perspective_id: number;
  user_id: number;
  verdict: GoNoGoOutcome;
  dissent_note?: string | null;
}

export interface GoNoGoConditionCreate {
  text: string;
  owner_user_id?: number | null;
  due_date?: string | null;
}

export interface GoNoGoDecisionCreate {
  outcome: GoNoGoOutcome;
  rationale: string;
  decided_at: string;
  attendees?: number[];
  signoffs?: GoNoGoSignoffCreate[];
  conditions?: GoNoGoConditionCreate[];
}

export interface GoNoGoSignoffRead {
  id: number;
  decision_id: number;
  perspective_id: number;
  user_id: number;
  username: string | null;
  // Resolved server-side, from the perspective's CURRENT name — see
  // `go_no_go_service.perspective_names_for`'s docstring: a rename changes
  // what an old decision's sign-off displays too, deliberately.
  perspective_name: string | null;
  verdict: string;
  dissent_note: string | null;
}

export interface GoNoGoConditionRead {
  id: number;
  decision_id: number;
  text: string;
  owner_user_id: number | null;
  owner_username: string | null;
  due_date: string | null;
  met_at: string | null;
  met_by_user_id: number | null;
  met_by_username: string | null;
}

/** PATCH body for `/go-no-go-conditions/{id}`. `met: false` reopens a
 * condition marked met in error. */
export interface GoNoGoConditionClose {
  met: boolean;
}

/** The snapshot's own findings are a reduced `{type, detail}` shape —
 * `go_no_go_service.record_decision` narrows `release_readiness_service.
 * evaluate`'s full `ReadinessBlocker`/`ReadinessWarning` down to just these
 * two fields when freezing the snapshot, so this is NOT the same type as
 * `ReadinessBlocker`/`ReadinessWarning` in `types/gateReadiness.ts`. */
export interface GoNoGoSnapshotFinding {
  type: string;
  detail: string | null;
}

export interface GoNoGoDecisionRead {
  id: number;
  tenant_id: number;
  release_id: number;
  outcome: string;
  rationale: string;
  decided_at: string;
  chaired_by_user_id: number;
  chaired_by_username: string | null;
  attendees: number[];
  // Resolved 1:1 with `attendees`, same order.
  attendee_usernames: string[];
  snapshot_ok: boolean;
  snapshot_blockers: GoNoGoSnapshotFinding[];
  snapshot_warnings: GoNoGoSnapshotFinding[];
  snapshot_reversibility: string | null;
  snapshot_rehearsal_state: string | null;
  signoffs: GoNoGoSignoffRead[];
  conditions: GoNoGoConditionRead[];
  unmet_condition_count: number;
}

export interface GoNoGoPerspectiveCreate {
  name: string;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

/** Optional fields + `exclude_unset` server-side: an omitted key means
 * "leave alone", same rule `EnvironmentUpdate`/`GateTypeUpdate` follow. */
export interface GoNoGoPerspectiveUpdate {
  name?: string;
  description?: string | null;
  sort_order?: number;
  is_active?: boolean;
}

export interface GoNoGoPerspectiveRead {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  sort_order: number;
  is_active: boolean;
}
