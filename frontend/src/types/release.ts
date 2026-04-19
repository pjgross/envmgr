export type ReleaseStatus = string;
export type ReleaseKind = 'project' | 'enterprise';

export interface ReleaseResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  release_type: string;
  release_kind: ReleaseKind;
  parent_release_id: number | null;
  template_id: number | null;
  lifecycle_template_id: number;
  status: ReleaseStatus;
  target_date: string | null;
  actual_date: string | null;
  custom_fields: Record<string, unknown> | null;
  raised_by: number;
  created_at: string;
  updated_at: string;
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

export interface ReleaseGateResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  test_phase_id: number | null;
  name: string;
  acceptance_criteria: string | null;
  status: 'pending' | 'passed' | 'failed' | 'overridden';
  decided_by: number | null;
  decided_at: string | null;
  decision_notes: string | null;
}

export interface ReleaseSystemResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  system_id: number;
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
  template_id?: number | null;
  lifecycle_template_id?: number | null;
  target_date?: string | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface ReleaseUpdatePayload {
  name?: string;
  description?: string | null;
  release_type?: string;
  target_date?: string | null;
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
  from_date?: string;
  to_date?: string;
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
  test_phase_id?: number | null;
  acceptance_criteria?: string | null;
}

export interface ReleaseGateUpdatePayload {
  name?: string;
  test_phase_id?: number | null;
  acceptance_criteria?: string | null;
}

export interface ReleaseGateDecisionPayload {
  notes?: string | null;
}

export interface ReleaseSystemCreatePayload {
  system_id: number;
  role: string;
  deployment_date?: string | null;
}

export interface ReleaseDependencyCreatePayload {
  depends_on_release_id: number;
  kind?: string;
  notes?: string | null;
}

export interface ReleaseCalendarEntry {
  release_id: number;
  release_name: string;
  phase_id: number;
  phase_name: string;
  start_date: string | null;
  end_date: string | null;
  status: string;
}

export interface ReleaseTimelineEntry {
  id: number;
  name: string;
  status: string;
  target_date: string | null;
  actual_date: string | null;
  phases: TestPhaseResponse[];
  dependencies: ReleaseDependencyResponse[];
}

export interface ReleaseBookingCreatePayload {
  environment_id: number;
  project_name: string;
  start_date: string;
  end_date: string;
  booking_type_id: number;
  test_phase_id?: number | null;
  exclusive_use?: boolean;
  notes?: string | null;
  custom_fields?: Record<string, unknown> | null;
}
