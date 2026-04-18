import type { AllowedTransition } from './bookingLifecycle';
import type { InfrastructureComponentSummary } from './infrastructureComponent';

export type ChangeType = 'configuration' | 'infrastructure' | 'code_deployment';

export const CHANGE_TYPE_LABELS: Record<ChangeType, string> = {
  configuration: 'Configuration',
  infrastructure: 'Infrastructure',
  code_deployment: 'Code Deployment',
};

export interface EnvironmentSummary {
  id: number;
  name: string;
}

export interface ChangeRequestResponse {
  id: number;
  tenant_id: number;
  title: string;
  description: string | null;
  change_type: ChangeType;
  status: string;
  lifecycle_id: number;
  subsystem_id: number | null;
  environment_ids: number[];
  host_ids: number[];
  environments: EnvironmentSummary[];
  hosts: InfrastructureComponentSummary[];
  derived_environment_ids: number[];
  release_id: number | null;
  has_outage: boolean;
  outage_start: string | null;
  outage_end: string | null;
  scheduled_start: string;
  scheduled_end: string;
  custom_fields: Record<string, unknown> | null;
  raised_by: number;
  created_at: string;
  updated_at: string;
}

export interface ChangeHistoryEntry {
  id: number;
  from_state: string | null;
  to_state: string | null;
  field_name: string | null;
  old_value: unknown | null;
  new_value: unknown | null;
  changed_by: number;
  changed_at: string;
  notes: string | null;
}

export interface ChangeRequestDetailResponse extends ChangeRequestResponse {
  history: ChangeHistoryEntry[];
}

export interface ChangeRequestCreatePayload {
  title: string;
  description?: string | null;
  change_type: ChangeType;
  lifecycle_id: number;
  subsystem_id?: number | null;
  environment_ids?: number[];
  host_ids?: number[];
  release_id?: number | null;
  has_outage?: boolean;
  outage_start?: string | null;
  outage_end?: string | null;
  scheduled_start: string;
  scheduled_end: string;
  custom_fields?: Record<string, unknown> | null;
}

export interface ChangeRequestUpdatePayload {
  title?: string;
  description?: string | null;
  change_type?: ChangeType;
  subsystem_id?: number | null;
  environment_ids?: number[];
  host_ids?: number[];
  release_id?: number | null;
  has_outage?: boolean;
  outage_start?: string | null;
  outage_end?: string | null;
  scheduled_start?: string;
  scheduled_end?: string;
  custom_fields?: Record<string, unknown> | null;
}

export interface ChangeRequestTransitionPayload {
  to_state: string;
  notes?: string | null;
}

export interface ChangeRequestListFilters {
  environment_id?: number;
  host_id?: number;
  subsystem_id?: number;
  status?: string;
  scheduled_from?: string;
  scheduled_to?: string;
}

export interface OutageConflictBooking {
  id: number;
  environment_id: number;
  environment_name: string;
  project_name: string;
  start_date: string;
  end_date: string;
  status: string;
}

export interface OutageConflictEnvironment {
  environment_id: number;
  environment_name: string;
  conflicts: OutageConflictBooking[];
}

export interface PreviewOutageConflictsPayload {
  environment_ids?: number[];
  host_ids?: number[];
  outage_start: string;
  outage_end: string;
  exclude_change_request_id?: number | null;
}

export interface PreviewOutageConflictsResponse {
  environments: OutageConflictEnvironment[];
  derived_environment_ids: number[];
}

export type { AllowedTransition };
