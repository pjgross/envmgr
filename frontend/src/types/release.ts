import type { GateCriterion } from './gateCriterion';
import type { GateWaiverResponse } from './gateWaiver';

export type ReleaseStatus = string;
export type ReleaseKind = 'project' | 'enterprise';

export interface ReleaseResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  release_type: string;
  release_kind: ReleaseKind;
  owning_project_id: number | null;
  owning_project_name: string | null;
  parent_release_id: number | null;
  template_id: number | null;
  lifecycle_template_id: number;
  status: ReleaseStatus;
  target_date: string | null;
  actual_date: string | null;
  scope_deadline: string | null;
  scope_creep_count?: number;
  custom_fields: Record<string, unknown> | null;
  raised_by: number;
  created_at: string;
  updated_at: string;
}

export interface ReleaseSystemBrief {
  id: number;
  name: string;
  role: 'changing' | 'regression' | 'config_only';
}

/** List endpoint response — includes denormalised summary counts */
export interface ReleaseListItemResponse extends ReleaseResponse {
  phase_count: number;
  scope_count: number;
  blocker_count: number;
  overdue_criterion_count: number;
  scope_additions_count: number;
  scope_removals_count: number;
  scope_change_count: number;
  scope_creep_count: number;
  window_status: 'open' | 'closing_soon' | 'closed' | 'shipped' | 'no_cutoff';
  days_to_cutoff: number | null;
  systems: ReleaseSystemBrief[];
}

export interface TestPhaseResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  name: string;
  order: number;
  start_date: string | null;
  end_date: string | null;
  status: string;
}

export interface TimelineGate {
  id: number;
  name: string;
  due_date: string;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
}

export interface ReleaseGateResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  due_date: string;
  name: string;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
  decided_by: number | null;
  decided_at: string | null;
  decision_notes: string | null;
  /** Phase 9 C2 — which GateType (tenant vocabulary) this gate is typed as, or null for untyped. */
  gate_type_id: number | null;
  test_phase_id: number | null;
  criteria: GateCriterion[];
  overdue_criterion_count: number;
  /**
   * Task 10c. Populated only for an `overridden` gate — the current waiver
   * for it, or null (no waiver record at all: a pending/passed/failed gate,
   * or a gate overridden before C2 shipped waiver tracking). Required, no
   * default — a fixture or construction site that forgets it is a compile
   * error, not a silently-null field (see GateWaiverRead's own docstring on
   * the backend for the construction-site trap this guards against).
   */
  waiver: GateWaiverResponse | null;
}

export interface ReleaseSystemResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  system_id: number;
  system_name: string | null;
  role: 'changing' | 'regression' | 'config_only';
  deployment_date: string | null;
}

export interface ReleaseDependencyResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  depends_on_release_id: number;
  kind: string;
  notes: string | null;
  last_dependency_target_date: string | null;
}

export interface ReleaseDependencyAlert {
  dependency_id: number;
  depends_on_release_id: number;
  depends_on_name: string;
  prior_target_date: string | null;
  current_target_date: string | null;
  diff_days: number;
}

export interface ReleaseStatusHistory {
  id: number;
  release_id: number;
  from_state: string | null;
  to_state: string;
  changed_by: number;
  changed_at: string;
  notes: string | null;
}

export interface ReleaseCreatePayload {
  name: string;
  description?: string | null;
  release_type: string;
  release_kind?: ReleaseKind;
  owning_project_id?: number | null;
  template_id?: number | null;
  lifecycle_template_id?: number | null;
  target_date?: string | null;
  scope_deadline?: string | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ReleaseUpdatePayload {
  name?: string;
  description?: string | null;
  release_type?: string;
  owning_project_id?: number | null;
  target_date?: string | null;
  scope_deadline?: string | null;
  actual_date?: string | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ReleaseTransitionPayload {
  to_state: string;
  notes?: string | null;
}

export interface ReleaseListFilters {
  status?: string;
  release_type?: string;
  release_kind?: ReleaseKind;
  date_from?: string;
  date_to?: string;
  system_id?: number | string;
  project_id?: number | string;
  search?: string;
  /**
   * `actionable` narrows to releases whose scope window is open or closing
   * soon. `all` (and omitting it) applies no window filter.
   */
  scope_window?: 'actionable' | 'all';
  limit?: number;
  offset?: number;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
}

export interface TestPhaseCreatePayload {
  name: string;
  order?: number;
  start_date?: string | null;
  end_date?: string | null;
  status?: string;
}

export interface TestPhaseUpdatePayload {
  name?: string;
  order?: number;
  start_date?: string | null;
  end_date?: string | null;
  status?: string;
}

export interface ReleaseGateCreatePayload {
  name: string;
  due_date: string;
}

export interface ReleaseGateUpdatePayload {
  name?: string;
  due_date?: string;
  // PUT /gates/{id} is extra="forbid" and keys on model_fields_set: an
  // OMITTED key means "leave alone", only an explicit null clears it.
  gate_type_id?: number | null;
  test_phase_id?: number | null;
}

export interface ReleaseGateDecisionPayload {
  notes?: string | null;
  // The three fields below only apply to POST /gates/{id}/override (a
  // waiver) — pass/fail ignore them if sent. expires_at: null (or omitted)
  // means a permanent waiver, a legitimate state, mirroring the backend's
  // ReleaseGateDecision.
  expires_at?: string | null;
  remediation?: string | null;
  approved_by_user_id?: number | null;
}

export interface ReleaseSystemCreatePayload {
  system_id: number;
  role: 'changing' | 'regression' | 'config_only';
  deployment_date?: string | null;
}

export interface ReleaseDependencyCreatePayload {
  depends_on_release_id: number;
  kind?: string;
  notes?: string | null;
}

export interface ReleaseCalendarEntry {
  /** Release id (backend key: id). */
  id: number;
  /** Release name (backend key: title). */
  title: string;
  start: string | null;
  end: string | null;
  status: string;
  release_type: string;
}

export interface ReleaseTimelineEntry {
  id: number;
  name: string;
  status: string;
  target_date: string | null;
  actual_date: string | null;
  phases: TestPhaseResponse[];
  gates: TimelineGate[];
  /** Backend may omit this when a release has no dependencies. */
  dependencies?: ReleaseDependencyResponse[];
}

export interface ReleaseBookingCreatePayload {
  environment_id: number;
  project_name?: string | null;
  /** Backend field name is `start` (not start_date) — ReleaseBookingRequest schema. */
  start: string;
  /** Backend field name is `end` (not end_date). */
  end: string;
  booking_type_id: number;
  /** Backend field name is `phase_id` (not test_phase_id) on the ReleaseBookingRequest. */
  phase_id?: number | null;
  exclusive_use?: boolean;
  notes?: string | null;
}

export interface ReleaseBulkBookingPayload {
  environment_ids: number[];
  phase_id?: number | null;
  start: string;
  end: string;
  booking_type_id: number;
  project_name?: string | null;
  notes?: string | null;
  exclusive_use?: boolean;
}

export interface BulkBookCreatedItem {
  environment_id: number;
  booking_id: number;
  warnings: number[];
}

export interface BulkBookSkippedItem {
  environment_id: number;
  conflicts: number[];
  reason?: string | null;
}

export interface BulkBookResultResponse {
  created: BulkBookCreatedItem[];
  skipped: BulkBookSkippedItem[];
}

export interface CoverageSystemResponse {
  system_id: number;
  system_name: string;
  role: 'changing' | 'regression';
}

export interface CoverageEnvironmentResponse {
  environment_id: number;
  name: string;
  tier_name: string;
  status: string;
  covered_system_ids: number[];
}

export interface ReleaseEnvironmentCoverageResponse {
  needed_systems: CoverageSystemResponse[];
  environments: CoverageEnvironmentResponse[];
  uncovered_system_ids: number[];
}

export interface ChurnCohortResponse {
  count: number;
  delayed_count: number;
  delayed_pct: number;
  issue_count: number;
  issue_pct: number;
}

export interface ChurnReleaseRowResponse {
  release_id: number;
  name: string;
  shipped_at: string;
  scope_changed: boolean;
  delayed: boolean;
  had_issue: boolean;
}

export interface ScopeChurnAnalyticsResponse {
  date_from: string | null;
  date_to: string | null;
  scope_changed: ChurnCohortResponse;
  stable: ChurnCohortResponse;
  releases: ChurnReleaseRowResponse[];
}
