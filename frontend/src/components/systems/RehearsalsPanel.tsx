/**
 * RehearsalsPanel — the rollback-rehearsal history for one system (Phase 9
 * C4, task 4's GET/POST .../rollback-rehearsals), rendered on the system
 * detail page.
 *
 * Without this panel, rehearsals are API-only — Task 4 built the endpoints
 * and nothing in the product reaches them. That is the "built it and
 * connected it to nothing" defect this sub-project's own docs call out by
 * name.
 *
 * MUST RENDER HONESTLY: a `failed` outcome is never presented as a pass, and
 * a STALE rehearsal must be visibly distinct from a CURRENT one — the
 * readiness verdict treats both `failed` and `stale` as "no successful
 * rehearsal", so a green tick beside either here would contradict the
 * release banner. `state` ('current'/'stale') is computed by the backend on
 * every read (rollback_rehearsal_service.rehearsal_state) — never
 * re-derived here.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchRehearsals, recordRehearsal } from '../../store/rollbackSlice';
import { formatBookingDateTime, toDateTimeLocal } from '../../utils/datetime';
import type { RehearsalOutcome } from '../../types/rollback';

interface Props {
  systemId: number;
}

const OUTCOME_LABEL: Record<string, string> = {
  passed: 'Passed',
  failed: 'Failed',
  partial: 'Partial',
};

const OUTCOME_COLOR: Record<string, 'success' | 'error' | 'warning'> = {
  passed: 'success',
  failed: 'error',
  partial: 'warning',
};

export default function RehearsalsPanel({ systemId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { rehearsals, rehearsalsLoading, rehearsalsError } = useSelector(
    (s: RootState) => s.rollback
  );

  const [recordOpen, setRecordOpen] = useState(false);
  const [rehearsedAt, setRehearsedAt] = useState('');
  const [outcome, setOutcome] = useState<RehearsalOutcome>('passed');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchRehearsals(systemId));
  }, [dispatch, systemId]);

  useEffect(() => {
    if (!recordOpen) return;
    setRehearsedAt(toDateTimeLocal(new Date()));
    setOutcome('passed');
    setNotes('');
    setError(null);
  }, [recordOpen]);

  // Backend orders rehearsed_at DESC, id DESC and every new record is
  // unshifted onto the front the same way — the first element is always the
  // latest.
  const latest = rehearsals[0] ?? null;
  // Honest by construction: only a PASSED and CURRENT latest rehearsal gets
  // this marker. A failed or stale one must never render it — see the
  // module docstring.
  const latestIsHealthy = latest?.outcome === 'passed' && latest?.state === 'current';

  const handleSave = async () => {
    if (!rehearsedAt) return;
    setSaving(true);
    setError(null);
    const result = await dispatch(
      recordRehearsal({
        systemId,
        data: {
          rehearsed_at: new Date(rehearsedAt).toISOString(),
          outcome,
          notes: notes.trim() ? notes.trim() : null,
        },
      })
    );
    setSaving(false);
    if (recordRehearsal.rejected.match(result)) {
      setError(result.payload ?? 'Failed to record the rehearsal');
      return;
    }
    setRecordOpen(false);
  };

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 2 }}>
        <Typography variant="h6">Rollback Rehearsals</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" onClick={() => setRecordOpen(true)}>
          Record a rehearsal
        </Button>
      </Stack>

      {rehearsalsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {rehearsalsError}
        </Alert>
      )}

      {latest && (
        <Alert
          severity={latestIsHealthy ? 'success' : latest.outcome === 'failed' ? 'error' : 'warning'}
          sx={{ mb: 2 }}
          {...(latestIsHealthy ? { 'data-testid': 'rehearsal-current' } : {})}
        >
          Latest rehearsal: {formatBookingDateTime(latest.rehearsed_at)} —{' '}
          {OUTCOME_LABEL[latest.outcome] ?? latest.outcome},{' '}
          {latest.state === 'current' ? 'current' : 'stale'}.
          {latest.outcome === 'failed' &&
            ' A failed rehearsal is not a pass — the readiness verdict treats it as no successful rehearsal at all.'}
          {latest.outcome !== 'failed' && latest.state === 'stale' &&
            ' Stale rehearsals no longer count as evidence for the readiness verdict.'}
        </Alert>
      )}
      {!latest && !rehearsalsLoading && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          No rollback rehearsal has ever been recorded for this system.
        </Alert>
      )}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Date</TableCell>
            <TableCell>Run by</TableCell>
            <TableCell>Outcome</TableCell>
            <TableCell>Freshness</TableCell>
            <TableCell>Notes</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rehearsals.map((r) => (
            <TableRow key={r.id}>
              <TableCell>{formatBookingDateTime(r.rehearsed_at)}</TableCell>
              <TableCell>{r.rehearsed_by_username ?? '—'}</TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={OUTCOME_LABEL[r.outcome] ?? r.outcome}
                  color={OUTCOME_COLOR[r.outcome]}
                />
              </TableCell>
              <TableCell>
                <Chip
                  size="small"
                  label={r.state === 'current' ? 'Current' : 'Stale'}
                  color={r.state === 'current' ? 'success' : 'default'}
                  variant={r.state === 'current' ? 'filled' : 'outlined'}
                />
              </TableCell>
              <TableCell>{r.notes ?? '—'}</TableCell>
            </TableRow>
          ))}
          {rehearsals.length === 0 && !rehearsalsLoading && (
            <TableRow>
              <TableCell colSpan={5}>
                <Typography color="text.secondary">No rehearsals recorded yet.</Typography>
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={recordOpen} onClose={() => setRecordOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Record a Rollback Rehearsal</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            label="Rehearsed at"
            type="datetime-local"
            value={rehearsedAt}
            onChange={(e) => setRehearsedAt(e.target.value)}
            disabled={saving}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            select
            label="Outcome"
            value={outcome}
            onChange={(e) => setOutcome(e.target.value as RehearsalOutcome)}
            disabled={saving}
          >
            <MenuItem value="passed">Passed</MenuItem>
            <MenuItem value="failed">Failed</MenuItem>
            <MenuItem value="partial">Partial</MenuItem>
          </TextField>
          <TextField
            label="Notes"
            multiline
            minRows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={saving}
            helperText="A failed or partial rehearsal is recorded exactly as faithfully as a passed one — it's still evidence rolling this back was tried."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRecordOpen(false)} disabled={saving}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSave} disabled={!rehearsedAt || saving}>
            Save
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
