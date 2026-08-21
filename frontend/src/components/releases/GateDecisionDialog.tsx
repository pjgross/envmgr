/**
 * GateDecisionDialog — lets the user pass, fail, or override a release gate.
 */
import { useState } from 'react';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../../store';
import { passGate, failGate } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ReleaseGateResponse } from '../../types/release';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  gate: ReleaseGateResponse | null;
  /**
   * 'override' used to be a third decision here, behind a bare notes field.
   * Task 10b replaced it with WaiverDialog (reason/approver/expiry/
   * remediation) — this button closes this dialog and hands off to it,
   * rather than adding a fourth always-visible control to GatesTable's
   * already-dense row.
   */
  onWaiveInstead: () => void;
}

type Decision = 'pass' | 'fail';

export default function GateDecisionDialog({ open, onClose, releaseId, gate, onWaiveInstead }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!gate) return null;

  const handleDecision = async (decision: Decision) => {
    setSubmitting(true);
    try {
      const payload = { notes: notes.trim() || undefined };
      if (decision === 'pass') {
        await dispatch(passGate({ releaseId, gateId: gate.id, data: payload })).unwrap();
      } else {
        await dispatch(failGate({ releaseId, gateId: gate.id, data: payload })).unwrap();
      }
      snackbar.success(`Gate ${decision}ed`);
      setNotes('');
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to record gate decision');
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    if (submitting) return;
    setNotes('');
    onClose();
  };

  const handleWaiveInstead = () => {
    if (submitting) return;
    setNotes('');
    onClose();
    onWaiveInstead();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>Gate Decision — {gate.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <TextField
            label="Notes (optional)"
            multiline
            rows={3}
            fullWidth
            size="small"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={submitting}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          color="warning"
          disabled={submitting}
          onClick={handleWaiveInstead}
        >
          Waive instead
        </Button>
        <Button
          color="error"
          disabled={submitting}
          onClick={() => handleDecision('fail')}
        >
          Fail
        </Button>
        <Button
          color="success"
          variant="contained"
          disabled={submitting}
          onClick={() => handleDecision('pass')}
        >
          Pass
        </Button>
      </DialogActions>
    </Dialog>
  );
}
