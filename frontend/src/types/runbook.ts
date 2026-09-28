// Phase 9 C5a — mirrors backend/app/api/v1/schemas/runbook.py exactly.
export type TaskStatus = 'not_started' | 'in_progress' | 'done' | 'failed' | 'skipped';
export type TaskKind = 'task' | 'check' | 'deploy' | 'verification' | 'ramp';
export type DeployPattern = 'rolling' | 'blue_green' | 'canary' | 'big_bang' | 'other';
// Backend schema types `state` as plain `str` (schemas/runbook.py:81), not a
// Literal — runbook_schedule_service.plan_state() is the sole producer and its
// only four return values are exactly this set, kept here for documentation.
export type PlanState = 'not_started' | 'in_progress' | 'complete' | 'failed';

export interface RunbookPlanRead {
  id: number;
  release_id: number;
  environment_id: number;
  environment_name: string | null;
  name: string;
  anchor_start_at: string;
  deploy_pattern: DeployPattern | null;
  notes: string | null;
  state: string;
}

export interface RunbookTaskRead {
  id: number;
  name: string;
  description: string | null;
  kind: TaskKind;
  team_group_id: number | null;
  team_name: string | null;
  system_id: number | null;
  system_name: string | null;
  system_on_release: boolean;
  duration_minutes: number;
  fixed_start_at: string | null;
  status: TaskStatus;
  actual_started_at: string | null;
  actual_finished_at: string | null;
  sort_order: number;
  predecessor_ids: number[];
  planned_start: string;
  planned_finish: string;
  forecast_start: string;
  forecast_finish: string;
  late_start: boolean;
  overrunning: boolean;
  slipped_past_fixed_start: boolean;
  blocked: boolean;
  critical: boolean;
  allowed_transitions: TaskStatus[];
}

export interface RunbookRead {
  plan: RunbookPlanRead;
  planned_end: string;
  forecast_end: string;
  slip_minutes: number;
  tasks: RunbookTaskRead[];
}

export interface RunbookTaskEventRead {
  id: number;
  from_status: TaskStatus;
  to_status: TaskStatus;
  at: string;
  recorded_at: string;
  by_username: string | null;
  note: string | null;
}

export interface RunbookPlanCreate {
  environment_id: number;
  name: string;
  anchor_start_at: string;
  deploy_pattern?: DeployPattern | null;
  notes?: string | null;
}
export type RunbookPlanUpdate = Partial<Omit<RunbookPlanCreate, 'environment_id'>>;

export interface RunbookTaskCreate {
  name: string;
  description?: string | null;
  team_group_id?: number | null;
  system_id?: number | null;
  kind?: TaskKind;
  duration_minutes: number;
  fixed_start_at?: string | null;
  sort_order?: number;
  predecessor_ids?: number[];
}
export type RunbookTaskUpdate = Partial<Omit<RunbookTaskCreate, 'predecessor_ids'>>;

export interface TransitionRequest {
  to_status: TaskStatus;
  at?: string | null;
  reason?: string | null;
}
