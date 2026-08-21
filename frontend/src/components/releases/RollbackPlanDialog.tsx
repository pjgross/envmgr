/**
 * RollbackPlanDialog — create or edit the rollback plan for ONE component of
 * a release (Phase 9 C4, task 2's PUT .../rollback-plans, an upsert keyed on
 * (release_id, system_id)).
 *
 * Editing the steps or reversibility of an already-agreed plan clears the
 * agreement server-side — a plan a sponsor agreed to and someone then
 * rewrote is not the plan they agreed to. This dialog says so rather than
 * silently discarding the sign-off.
 */
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';

import type { AppDispatch } from '../../store';
import { upsertRollbackPlan } from '../../store/rollbackSlice';
import type { Reversibility, RollbackPlanResponse } from '../../types/rollback';

interface Props {
  releaseId: number;
  systemId: number;
  systemName?: string | null;
  plan?: RollbackPlanResponse | null;
  open: boolean;
  onClose: () => void;
  /**
   * Called once the save has actually succeeded server-side, before onClose.
   * Distinct from onClose (which also fires on Cancel) — the caller uses
   * this to know a plan mutation really happened, e.g. to refetch the
   * release's readiness verdict, which recomputes reversibility server-side.
   */
  onSaved?: () => void;
}

const REVERSIBILITY_OPTIONS: { value: Reversibility; label: string }[] = [
  { value: 'reversible', label: 'Reversible' },
  { value: 'lossy', label: 'Lossy' },
  { value: 'irreversible', label: 'Irreversible' },
];

export default function RollbackPlanDialog({
  releaseId,
  systemId,
  systemName,
  plan,
  open,
  onClose,
  onSaved,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();

  const [steps, setSteps] = useState('');
  const [reversibility, setReversibility] = useState<Reversibility>('reversible');
  const [estimatedMinutes, setEstimatedMinutes] = useState('');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed from the plan being edited every time the dialog opens — not
  // just on mount, since the same dialog instance may be reused for
  // different rows/components.
  useEffect(() => {
    if (!open) return;
    setSteps(plan?.steps ?? '');
    setReversibility((plan?.reversibility as Reversibility) ?? 'reversible');
    setEstimatedMinutes(
      plan?.estimated_minutes != null ? String(plan.estimated_minutes) : ''
    );
    setNotes(plan?.notes ?? '');
    setError(null);
  }, [open, plan]);

  const handleSave = async () => {
    if (!steps.trim()) return;
    setSaving(true);
    setError(null);
    const result = await dispatch(
      upsertRollbackPlan({
        releaseId,
        data: {
          system_id: systemId,
          steps: steps.trim(),
          reversibility,
          estimated_minutes: estimatedMinutes.trim() ? Number(estimatedMinutes) : null,
          notes: notes.trim() ? notes.trim() : null,
        },
      })
    );
    setSaving(false);
    if (upsertRollbackPlan.rejected.match(result)) {
      // result.payload holds formatApiError's text — never
      // result.error.message, which for a real AxiosError would be the
      // generic "Request failed with status code N" and drop the server's
      // actual reason.
      setError(result.payload ?? 'Failed to save the rollback plan');
      return;
    }
    onSaved?.();
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        {plan ? 'Edit' : 'New'} Rollback Plan{systemName ? ` — ${systemName}` : ''}
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {plan?.agreed_at && (
          <Alert severity="info">
            This plan is agreed. Changing the steps or reversibility below clears that
            agreement — the plan someone agreed to is what it said, not what it becomes.
          </Alert>
        )}
        <TextField
          label="Steps"
          required
          multiline
          minRows={4}
          value={steps}
          onChange={(e) => setSteps(e.target.value)}
          disabled={saving}
          helperText="What to actually do, in order, to roll this component back."
        />
        <TextField
          select
          label="Reversibility"
          value={reversibility}
          onChange={(e) => setReversibility(e.target.value as Reversibility)}
          disabled={saving}
        >
          {REVERSIBILITY_OPTIONS.map((o) => (
            <MenuItem key={o.value} value={o.value}>
              {o.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="Estimated time (minutes)"
          type="number"
          value={estimatedMinutes}
          onChange={(e) => setEstimatedMinutes(e.target.value)}
          disabled={saving}
          inputProps={{ min: 0 }}
        />
        <TextField
          label="Notes"
          multiline
          minRows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={saving}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={!steps.trim() || saving}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
