/**
 * Gate evidence (Phase 9 C2, task 10b) — a reference vouching for a gate:
 * a test report, a runbook, a licence document, ... optionally naming the
 * deployment it was produced against.
 *
 * `kind` is free text on the backend (see `GateEvidenceCreate` in
 * `backend/app/api/v1/schemas/gate_evidence.py`) — a gate type's
 * `expected_evidence` is offered as a set of choices, but an unlisted kind
 * is accepted and simply satisfies no expectation. The frontend type
 * mirrors that: `kind: string`, never a union.
 */
export interface GateEvidenceResponse {
  id: number;
  gate_id: number;
  kind: string;
  label: string;
  url: string | null;
  notes: string | null;
  deployment_id: number | null;
  added_by: number;
  created_at: string;
  /**
   * Required, no default, mirroring the backend's own reasoning
   * (`GateEvidenceRead.is_stale` docstring): a field that could silently
   * default to `false` is how "stale" ships permanently wrong.
   */
  is_stale: boolean;
}

export interface GateEvidenceCreatePayload {
  kind: string;
  label: string;
  url?: string | null;
  notes?: string | null;
  deployment_id?: number | null;
}
