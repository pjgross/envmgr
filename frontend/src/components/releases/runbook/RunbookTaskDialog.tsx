/**
 * Placeholder — Task 10 replaces this with the real create/edit dialog for a
 * runbook task. The prop signature is final so RunbookTab (Task 9) compiles
 * and its tests run against the eventual shape.
 */
import type { RunbookRead, RunbookTaskRead } from '../../../types/runbook';

interface Props {
  read: RunbookRead;
  task?: RunbookTaskRead;
  onClose: () => void;
}

export default function RunbookTaskDialog(_props: Props) {
  return null;
}
