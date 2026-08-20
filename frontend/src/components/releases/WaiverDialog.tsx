/**
 * WaiverDialog — replaces the bare override-notes prompt that used to live
 * in GateDecisionDialog. Reason is required (the backend 422s on empty
 * notes); approver and expiry are optional, and an empty expiry is a
 * legitimate PERMANENT waiver, not a missing value.
 *
 * There is no `GET .../waiver` endpoint (see `backend/app/services/
 * gate_waiver_service.py` — the current waiver is only ever read back
 * through the readiness verdict's summarised text, batched for a whole
 * page). So "show an existing waiver" here means what this view genuinely
 * has: the gate's own decision fields (`decision_notes`, `decided_by`,
 * `decided_at`) when the gate is already `overridden` — not a re-read of
 * the waiver row's approver/expiry, which this page cannot fetch. Submitting
 * again always records a NEW waiver row (the backend's own model: rows
 * accumulate as history, nothing is overwritten).
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import type { AppDispatch } from '../../store';
import { overrideGate } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { toIsoDatetime } from '../../utils/dates';
import WaiverChip from './WaiverChip';
import type { ReleaseGateResponse } from '../../types/release';

interface UserOption {
  id: number;
  username: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  gate: ReleaseGateResponse | null;
  users: UserOption[];
}

export default function WaiverDialog({ open, onClose, releaseId, gate, users }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();

  const [reason, setReason] = useState('');
  const [approver, setApprover] = useState<UserOption | null>(null);
  const [expiry, setExpiry] = useState(''); // "" = permanent
  const [remediation, setRemediation] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const previousOwner = useMemo(() => {
    if (!gate || gate.decided_by == null) return null;
    return users.find((u) => u.id === gate.decided_by) ?? null;
  }, [gate, users]);

  // Prefill the reason from the gate's own decision fields whenever the
  // dialog opens (or is re-opened for a different gate) — a fresh
  // re-waive starts from the existing text rather than a blank field.
  // Re-render, don't just mount: this must key on gate.id, not just
  // `open`, so switching gates while a similar dialog stays mounted
  // re-initialises rather than showing the previous gate's text.
  useEffect(() => {
    if (!open || !gate) return;
    setReason(gate.status === 'overridden' ? gate.decision_notes ?? '' : '');
    setApprover(null);
    setExpiry('');
    setRemediation('');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, gate?.id]);

  if (!gate) return null;

  const reset = () => {
    setReason('');
    setApprover(null);
    setExpiry('');
    setRemediation('');
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!reason.trim()) return;
    setSubmitting(true);
    try {
      const result = await dispatch(
        overrideGate({
          releaseId,
          gateId: gate.id,
          data: {
            notes: reason.trim(),
            // "" -> null: an empty expiry is a permanent waiver, sent
            // explicitly rather than an omitted key, per the API's own
            // documented meaning of null here.
            expires_at: toIsoDatetime(expiry),
            remediation: remediation.trim() || undefined,
            approved_by_user_id: approver?.id ?? undefined,
          },
        })
      );
      if (overrideGate.fulfilled.match(result)) {
        snackbar.success('Gate overridden');
        reset();
        onClose();
      } else {
        snackbar.error(result.payload ?? 'Failed to record the waiver');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Waive Gate — {gate.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {gate.status === 'overridden' && (
            <Alert severity="info">
              <Typography variant="body2" fontWeight="medium">
                Currently overridden
              </Typography>
              <Typography variant="body2">
                {previousOwner ? previousOwner.username : gate.decided_by ? `user #${gate.decided_by}` : 'someone'}
                {gate.decided_at ? ` on ${new Date(gate.decided_at).toLocaleDateString()}` : ''}
                {gate.decision_notes ? `: "${gate.decision_notes}"` : ''}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Submitting below records a new waiver.
              </Typography>
            </Alert>
          )}

          <Alert severity="warning" variant="outlined">
            A waived gate is overridden, not passed — it still reads as unmet
            work, recorded rather than resolved.
          </Alert>

          <TextField
            label="Reason"
            required
            multiline
            rows={3}
            fullWidth
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            disabled={submitting}
            helperText="Required — the server refuses an empty reason."
          />

          <Autocomplete
            options={users}
            getOptionLabel={(u) => u.username}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            value={approver}
            onChange={(_, v) => setApprover(v)}
            disabled={submitting}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Approver (optional)"
                helperText="Defaults to you if left blank."
              />
            )}
          />

          <Box>
            <TextField
              label="Expiry (optional)"
              type="date"
              fullWidth
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
              disabled={submitting}
              InputLabelProps={{ shrink: true }}
              helperText="Leave blank for a permanent waiver."
            />
            <Box sx={{ mt: 1 }}>
              <WaiverChip expiresAt={toIsoDatetime(expiry)} />
            </Box>
          </Box>

          <TextField
            label="Remediation (optional)"
            multiline
            rows={2}
            fullWidth
            value={remediation}
            onChange={(e) => setRemediation(e.target.value)}
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
          variant="contained"
          onClick={handleSubmit}
          disabled={submitting || !reason.trim()}
        >
          {submitting ? 'Waiving…' : 'Waive Gate'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
