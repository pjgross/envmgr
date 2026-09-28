import type { DeployPattern, TaskKind, TaskStatus } from '../../../types/runbook';

export const STATUS_LABEL: Record<TaskStatus, string> = {
  not_started: 'Not started', in_progress: 'In progress', done: 'Done', failed: 'Failed', skipped: 'Skipped',
};
export const STATUS_COLOR: Record<TaskStatus, 'default' | 'info' | 'success' | 'error' | 'warning'> = {
  not_started: 'default', in_progress: 'info', done: 'success', failed: 'error', skipped: 'warning',
};
export const KIND_LABEL: Record<TaskKind, string> = {
  task: 'Task', check: 'Check', deploy: 'Deploy', verification: 'Verification', ramp: 'Ramp',
};
export const PATTERN_LABEL: Record<DeployPattern, string> = {
  rolling: 'Rolling', blue_green: 'Blue-green', canary: 'Canary', big_bang: 'Big bang', other: 'Other',
};
/** The button text for moving a task to `to` from `from`. */
export function actionLabel(to: TaskStatus, from: TaskStatus): string {
  if (to === 'in_progress') return from === 'failed' ? 'Retry' : 'Start';
  if (to === 'done') return from === 'not_started' ? 'Mark done' : 'Complete';
  if (to === 'failed') return 'Fail';
  if (to === 'skipped') return 'Skip';
  return 'Reopen';
}
export const NEEDS_REASON = (to: TaskStatus) => to === 'skipped' || to === 'not_started';
export const FLAG_TEXT = {
  critical: 'On the critical path — a delay here moves the finish',
  late_start: 'Late start',
  overrunning: 'Overrunning its planned duration',
  slipped_past_fixed_start: 'Pushed past its fixed start time by earlier tasks',
  blocked: 'Blocked by a failed task',
} as const;
