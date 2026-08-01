/**
 * BulkBookEnvironmentsDialog — book several environments for a release at once,
 * with a conflict preview and a per-environment result summary.
 */
import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  MenuItem, Stack, TextField,
} from '@mui/material';
import { RootState } from '../../store';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { releaseService } from '../../services/releaseService';
import { bookingRequestService } from '../../services/bookingRequestService';
import { bookingLifecycleService } from '../../services/bookingLifecycleService';
import { phaseBookingDefaults } from './phaseBookingDefaults';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { TestPhaseResponse, BulkBookResultResponse } from '../../types/release';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';
import type { EnvBookingSummary } from '../../types/bookingRequest';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  environmentIds: number[];
  phases: TestPhaseResponse[];
  onCreated: () => void;
}

export default function BulkBookEnvironmentsDialog({
  open, onClose, releaseId, environmentIds, phases, onCreated,
}: Props) {
  const snackbar = useSnackbar();
  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page. This dialog only uses the
  // list to render display names for already-chosen environment ids, but the
  // same truncation hazard applies — a missing env would fall back to `#id`.
  const { environments } = useAllEnvironments();
  const releaseName = useSelector((s: RootState) => s.release.detail?.name ?? '');

  const [bookingTypes, setBookingTypes] = useState<BookingTypeRecord[]>([]);
  const [phaseId, setPhaseId] = useState<number | ''>('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [projectName, setProjectName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [conflicts, setConflicts] = useState<Record<number, EnvBookingSummary[]> | null>(null);
  const [result, setResult] = useState<BulkBookResultResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    bookingLifecycleService.listBookingTypes().then(setBookingTypes).catch(() => setBookingTypes([]));
  }, []);

  useEffect(() => {
    if (open) {
      setConflicts(null);
      setResult(null);
      setProjectName('');
      setStartDate('');
      setEndDate('');
      setBookingTypeId('');
      setPhaseId('');
    }
  }, [open, environmentIds]);

  const envName = useMemo(() => {
    const m = new Map<number, string>();
    environments.forEach((e) => m.set(e.id, e.name));
    return (id: number) => m.get(id) ?? `#${id}`;
  }, [environments]);

  // Choosing a phase defaults the project name and dates from that phase.
  const handlePhaseChange = (value: string) => {
    const id = value === '' ? '' : Number(value);
    setPhaseId(id);
    if (id === '') return;
    const phase = phases.find((p) => p.id === id);
    if (!phase) return;
    const defaults = phaseBookingDefaults(phase, releaseName);
    setProjectName(defaults.projectName);
    if (defaults.startDate) setStartDate(defaults.startDate);
    if (defaults.endDate) setEndDate(defaults.endDate);
  };

  const canPreview = !!startDate && !!endDate && environmentIds.length > 0;
  const canSubmit = canPreview && !!bookingTypeId && !!projectName.trim();

  const handlePreview = async () => {
    if (!canPreview) return;
    try {
      const resp = await bookingRequestService.previewConflicts({
        environment_ids: environmentIds,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
      });
      setConflicts(resp.conflicts);
    } catch {
      snackbar.error('Failed to check conflicts');
    }
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const res = await releaseService.bulkBookEnvironments(releaseId, {
        environment_ids: environmentIds,
        phase_id: phaseId !== '' ? (phaseId as number) : undefined,
        start: new Date(startDate).toISOString(),
        end: new Date(endDate).toISOString(),
        booking_type_id: bookingTypeId as number,
        project_name: projectName,
      });
      setResult(res);
      onCreated();
      if (res.created.length === 0) {
        snackbar.error(`No environments booked — ${res.skipped.length} skipped with a conflict`);
      } else if (res.skipped.length > 0) {
        snackbar.success(`Booked ${res.created.length}; skipped ${res.skipped.length} with a conflict`);
      } else {
        snackbar.success(`Booked ${res.created.length} environment(s)`);
      }
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? `${(detail[0] as { loc?: unknown[] }).loc?.join?.('.') ?? 'field'}: ${
              (detail[0] as { msg: string }).msg
            }`
          : err instanceof Error ? err.message : 'Failed to book environments';
      snackbar.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Book {environmentIds.length} environment(s)</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
            {environmentIds.map((id) => (
              <Chip key={id} label={envName(id)} size="small" />
            ))}
          </Box>

          <TextField select label="Test Phase (optional)" fullWidth value={phaseId}
            onChange={(e) => handlePhaseChange(e.target.value)}>
            <MenuItem value="">None</MenuItem>
            {phases.map((p) => (<MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>))}
          </TextField>

          <TextField select label="Booking Type" required fullWidth value={bookingTypeId}
            onChange={(e) => setBookingTypeId(Number(e.target.value))}>
            {bookingTypes.map((bt) => (<MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>))}
          </TextField>

          <TextField label="Project Name" required fullWidth value={projectName}
            onChange={(e) => setProjectName(e.target.value)} />

          <TextField label="Start Date" type="date" required fullWidth InputLabelProps={{ shrink: true }}
            value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          <TextField label="End Date" type="date" required fullWidth InputLabelProps={{ shrink: true }}
            value={endDate} onChange={(e) => setEndDate(e.target.value)} />

          <Button variant="outlined" onClick={handlePreview} disabled={!canPreview}>
            Check conflicts
          </Button>

          {conflicts && (
            Object.keys(conflicts).length === 0 ? (
              <Alert severity="success">No conflicts for the chosen window.</Alert>
            ) : (
              <Alert severity="warning">
                Conflicts detected:
                {Object.entries(conflicts).map(([envId, list]) => (
                  <div key={envId}>
                    <strong>{envName(Number(envId))}</strong>: {list.map((b) => b.project_name ?? `#${b.id}`).join(', ')}
                  </div>
                ))}
              </Alert>
            )
          )}

          {result && (
            <Alert severity={result.skipped.length > 0 ? 'warning' : 'success'}>
              Booked {result.created.length} environment(s).
              {result.skipped.length > 0 && (
                <div>
                  Skipped {result.skipped.length} with an exclusive conflict:{' '}
                  {result.skipped.map((s) => envName(s.environment_id)).join(', ')}
                </div>
              )}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>{result ? 'Close' : 'Cancel'}</Button>
        {!result && (
          <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit || submitting}>
            {submitting ? 'Booking…' : 'Book'}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
