/**
 * Placeholder — Task 10 replaces this with the real dialog for a transition
 * that needs a reason (`skipped`, or `not_started` = reopen) or an "actually
 * happened at" time (the Record time control on `done`). The prop signature
 * is final so RunbookTab (Task 9) compiles and its tests run against the
 * eventual shape.
 */
import type { RunbookTaskRead, TaskStatus } from '../../../types/runbook';

interface Props {
  planId: number;
  task: RunbookTaskRead;
  to: TaskStatus;
  onClose: () => void;
}

export default function RunbookTransitionDialog(_props: Props) {
  return null;
}
