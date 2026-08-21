/**
 * Gate waivers (Phase 9 C2, task 10c) — the record behind an overridden
 * gate, now readable rather than write-only. Mirrors
 * `backend/app/api/v1/schemas/release_gate.py`'s `GateWaiverRead` 1:1.
 *
 * `state` is computed server-side (`gate_waiver_service.waiver_state`) from
 * ONE clock per response — never re-derived per row here. There is no
 * `state` column on the backend row; trust the server's answer rather than
 * recomputing it from `expires_at` and the browser's own clock, which is
 * itself a stale-by-milliseconds source of exactly the "today reads as
 * overdue" bug `formatExpiry` already had to fix once.
 */
export interface GateWaiverResponse {
  id: number;
  reason: string;
  approved_by_user_id: number;
  approved_by_username: string | null;
  expires_at: string | null;
  remediation: string | null;
  created_at: string;
  state: 'live' | 'expired';
}
