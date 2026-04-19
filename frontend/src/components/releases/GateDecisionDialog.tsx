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
  Typography,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import { AppDispatch } from '../../store';
import { passGate, failGate, overrideGate } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ReleaseGateResponse } from '../../types/release';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  gate: ReleaseGateResponse | null;
}

type Decision = 'pass' | 'fail' | 'override';

export default function GateDecisionDialog({ open, onClose, releaseId, gate }: Props) {
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
      } else if (decision === 'fail') {
        await dispatch(failGate({ releaseId, gateId: gate.id, data: payload })).unwrap();
      } else {
        await dispatch(overrideGate({ releaseId, gateId: gate.id, data: payload })).unwrap();
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

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="xs" fullWidth>
      <DialogTitle>Gate Decision — {gate.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {gate.acceptance_criteria && (
            <Typography variant="body2" color="text.secondary">
              <strong>Criteria:</strong> {gate.acceptance_criteria}
            </Typography>
          )}
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
          color="error"
          disabled={submitting}
          onClick={() => handleDecision('fail')}
        >
          Fail
        </Button>
        <Button
          color="warning"
          disabled={submitting}
          onClick={() => handleDecision('override')}
        >
          Override
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
