/**
 * B5 — the environment decommissioning workflow, as the API renders it.
 * Mirrors backend/app/api/v1/schemas/decommission.py and
 * backend/app/core/decommission_states.py — read those before changing a
 * field here.
 */

/**
 * THESE ARE COMPUTED, NEVER STORED — there is no `state` column on
 * environment_decommission (see decommission_states.py's module docstring).
 * The five literals must match DECOMMISSION_STATES exactly.
 */
export type DecommissionState =
  | 'warned'
  | 'due'
  | 'extension_requested'
  | 'torn_down'
  | 'cancelled';

/**
 * One decommission, as `DecommissionRead` renders it. `state` is REQUIRED —
 * there is no column to default it from server-side, so an omission here
 * would compile and silently lie to every reader. Same rule
 * `Escalation.state` (A4) and `EnvBookingSummary.protection_level` (B4)
 * carry.
 */
export interface Decommission {
  id: number;
  environment_id: number;
  reason: string;
  warned_at: string;
  scheduled_teardown_at: string;
  initiated_by: number;

  extension_requested_at: string | null;
  extension_reason: string | null;
  extension_until: string | null;
  extension_decided_at: string | null;
  extension_granted: boolean | null;

  torn_down_at: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;

  state: DecommissionState;

  /**
   * Every attestation signed on this decommission, resolved server-side in
   * ONE join query (`environment_decommission_service.list_attestations`).
   * Present on `GET /environments/{id}/decommission` and every action
   * response; the worklist (`DecommissionWorklistRow`, which extends this
   * interface) always sends an empty array here rather than resolving it
   * per row — see that backend schema's own comment.
   *
   * OPTIONAL here, deliberately looser than the backend's REQUIRED field —
   * this field postdates several existing test fixtures across Tasks
   * 10/11 that build `Decommission`-shaped objects by hand, and widening
   * every one of them was out of scope for the fix that added this field.
   * Real responses always include it.
   */
  attestations?: Attestation[];
}

/** Body of `POST /environments/{id}/decommission` — initiating one. */
export interface DecommissionCreate {
  reason: string;
  /**
   * Optional: the initiator may push the teardown date LATER than the
   * tenant's notice period, never earlier. Omitted, the server computes it
   * as warned_at + policy.decommission_notice_days.
   */
  scheduled_teardown_at?: string;
}

/** Body of `POST /decommissions/{id}/extension` — the owner asking for more time. */
export interface ExtensionRequest {
  reason: string;
  until: string;
}

/**
 * Body of `POST /decommissions/{id}/extension/decision` — the operating
 * team's answer. Binary; no message field — a refusal's reasoning belongs in
 * conversation, not a stored column nothing renders (same call the backend
 * schema makes).
 */
export interface ExtensionDecision {
  granted: boolean;
}

/**
 * Body of `POST /decommissions/{id}/cancel` — the escape hatch. A reason is
 * required for the same audit-record reason `DecommissionCreate.reason` is.
 */
export interface CancelRequest {
  reason: string;
}

/** Body of `POST /decommissions/{id}/attestations` — one checklist step, confirmed. */
export interface AttestationCreate {
  step_key: string;
  /** Snapshot id, ticket, runbook link — free text, not parsed. */
  reference?: string | null;
  notes?: string | null;
}

/**
 * One signed checklist step, as `AttestationRead` renders it — what
 * `signAttestation` resolves with.
 */
export interface Attestation {
  id: number;
  decommission_id: number;
  step_key: string;
  signed_by: number;
  signed_at: string;
  reference: string | null;
  notes: string | null;
  /**
   * Resolved server-side (a LEFT JOIN in
   * `environment_decommission_service.list_attestations`) ONLY when this
   * came back as part of `Decommission.attestations` below — the bare
   * `POST .../attestations` response this type also describes validates
   * straight off the ORM row, which has no such column, so it is `null`
   * there. Optional/nullable rather than required: a signer whose `User`
   * row cannot be resolved (the join is deliberately NOT tenant-qualified,
   * but a row can still vanish) must not turn the whole response into a
   * validation failure.
   */
  signed_by_username?: string | null;
}

/**
 * One booking teardown did NOT touch. SURFACES, never touches — reporting it
 * is the point; nothing about it changes. Deliberately thin: a disclosure,
 * not a booking detail view.
 */
export interface RemainingBookingSummary {
  id: number;
  start_date: string;
  end_date: string;
  status: string;
}

/**
 * `POST /decommissions/{id}/teardown`'s response — a `Decommission` plus the
 * bookings still on the calendar for this environment. Teardown itself
 * changes none of their rows; this only names them.
 */
export interface TeardownResult extends Decommission {
  remaining_bookings: RemainingBookingSummary[];
}

/**
 * One row of `GET /decommissions` (the worklist) — a `Decommission` plus the
 * three names a worklist reader has never resolved themselves.
 *
 * THE NAMES TRAVEL WITH THE ROW, resolved server-side. A browser-side lookup
 * into a capped picker collection would lose a name past the cap —
 * information LOST, not merely hidden (see docs/pagination.md).
 */
export interface DecommissionWorklistRow extends Decommission {
  environment_name: string | null;
  initiated_by_username: string | null;
  owner_username: string | null;
}

/**
 * One tenant-configurable decommission checklist step, as
 * `DecommissionStepRead` renders it (`GET/POST/PATCH/DELETE
 * /tenant/decommission-steps` — a later task's own service, not this one).
 * Exported here because the detail panel renders these alongside a
 * decommission's signed attestations.
 */
export interface DecommissionStep {
  id: number;
  key: string;
  label: string;
  description: string | null;
  display_order: number;
  is_required: boolean;
  is_active: boolean;
}
