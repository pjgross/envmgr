/**
 * Phase 9 C2 — the gate readiness verdict for a release.
 *
 * Mirrors `backend/app/api/v1/schemas/gate_readiness.py` exactly. C2 ADVISES,
 * IT NEVER BLOCKS: a "blocker" here is a blocker in this VERDICT, which a
 * deployment pipeline may choose to obey via GET /webhooks/release-ready. It
 * does not stop a release transition, a deployment or a booking — see
 * backend/tests/test_c2_advises_never_blocks.py. Any component rendering
 * this response must say so; see ReadinessBanner.tsx.
 */

export type ReadinessBlockerType =
  | 'gate_pending'
  | 'gate_failed'
  | 'waiver_expired'
  // Phase 9 C4 — rollback governance. ref_kind 'system', no gate backs these.
  | 'rollback_plan_missing'
  | 'rollback_plan_unagreed'
  | 'rehearsal_missing'
  | 'rehearsal_stale';

export type ReadinessWarningType =
  | 'gate_waived'
  | 'gate_waived_no_record'
  | 'gate_untyped'
  | 'gate_pending'
  | 'gate_failed'
  | 'evidence_missing'
  | 'evidence_stale'
  // Phase 9 C4 — rollback governance. ref_kind 'system', no gate backs these.
  | 'rollback_plan_missing'
  | 'rollback_plan_unagreed'
  | 'rehearsal_missing'
  | 'rehearsal_stale'
  | 'rollback_irreversible'
  | 'rollback_lossy';

export interface ReadinessBlocker {
  type: ReadinessBlockerType;
  ref_kind: 'gate' | 'system';
  ref_id: number;
  // null at every rollback-finding construction site (release_readiness_
  // service._add) — no gate backs those. Their `detail` already names the
  // system, so ReadinessBanner must render `detail` alone rather than
  // treating a null name as a gate name.
  gate_name: string | null;
  gate_type: string | null;
  detail: string | null;
}

export interface ReadinessWarning {
  type: ReadinessWarningType;
  ref_kind: 'gate' | 'evidence' | 'system';
  ref_id: number;
  gate_name: string | null;
  gate_type: string | null;
  detail: string | null;
}

export interface ReleaseReadinessResponse {
  ok: boolean;
  release_id: number;
  checked_at: string;
  blockers: ReadinessBlocker[];
  warnings: ReadinessWarning[];
  // The worst reversibility across the release's rollback plans, or null if
  // there are none. Computed by rollback_plan_service.rollup.
  reversibility?: string | null;
}
