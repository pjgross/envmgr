/**
 * Placeholder — Task 10 replaces this with the real create/edit dialog for a
 * runbook plan. The prop signature is final so RunbookTab (Task 9) compiles
 * and its tests run against the eventual shape.
 */
import type { RunbookPlanRead } from '../../../types/runbook';

interface Props {
  releaseId: number;
  existing?: RunbookPlanRead;
  onClose: (createdId?: number) => void;
}

export default function RunbookPlanDialog(_props: Props) {
  return null;
}
