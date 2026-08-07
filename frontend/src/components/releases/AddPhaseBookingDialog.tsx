/**
 * AddPhaseBookingDialog — create a booking linked to a release phase.
 */
import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormHelperText,
  MenuItem,
  TextField,
} from '@mui/material';
import { RootState } from '../../store';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { releaseService } from '../../services/releaseService';
import { bookingLifecycleService } from '../../services/bookingLifecycleService';
import { phaseBookingDefaults } from './phaseBookingDefaults';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { TestPhaseResponse } from '../../types/release';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  phases: TestPhaseResponse[];
  onCreated: () => void;
  initialEnvironmentId?: number;
}

export default function AddPhaseBookingDialog({
  open,
  onClose,
  releaseId,
  phases,
  onCreated,
  initialEnvironmentId,
}: Props) {
  const snackbar = useSnackbar();
  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page, so this picker would silently
  // offer a subset. See useAllEnvironments's own doc comment.
  const { environments, truncated } = useAllEnvironments();
  const releaseName = useSelector((s: RootState) => s.release.detail?.name ?? '');

  const [bookingTypes, setBookingTypes] = useState<BookingTypeRecord[]>([]);
  const [envId, setEnvId] = useState<number | ''>('');
  const [phaseId, setPhaseId] = useState<number | ''>('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [projectName, setProjectName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    bookingLifecycleService
      .listBookingTypes()
      .then(setBookingTypes)
      .catch(() => setBookingTypes([]));
  }, []);

  useEffect(() => {
    if (open && initialEnvironmentId != null) {
      setEnvId(initialEnvironmentId);
    }
  }, [open, initialEnvironmentId]);

  const resetForm = () => {
    setEnvId('');
    setPhaseId('');
    setBookingTypeId('');
    setProjectName('');
    setStartDate('');
    setEndDate('');
  };

  const handleClose = () => {
    if (submitting) return;
    resetForm();
    onClose();
  };

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

  const handleSubmit = async () => {
    if (!envId || !bookingTypeId || !projectName || !startDate || !endDate) return;
    setSubmitting(true);
    try {
      await releaseService.bookForPhase(releaseId, {
        environment_id: envId as number,
        project_name: projectName,
        start: new Date(startDate).toISOString(),
        end: new Date(endDate).toISOString(),
        booking_type_id: bookingTypeId as number,
        phase_id: phaseId !== '' ? (phaseId as number) : undefined,
      });
      snackbar.success('Booking created');
      resetForm();
      onCreated();
      onClose();
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? `${(detail[0] as { loc?: unknown[] }).loc?.join?.('.') ?? 'field'}: ${
              (detail[0] as { msg: string }).msg
            }`
          : err instanceof Error ? err.message : 'Failed to create booking';
      snackbar.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const canSubmit =
    !!envId && !!bookingTypeId && !!projectName.trim() && !!startDate && !!endDate;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add Booking to Release</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          <TextField
            select
            label="Environment"
            required
            fullWidth
            value={envId}
            onChange={(e) => setEnvId(Number(e.target.value))}
          >
            {environments.map((e) => (
              <MenuItem key={e.id} value={e.id}>
                {e.name}
              </MenuItem>
            ))}
          </TextField>
          {truncated && (
            <FormHelperText sx={{ mt: -1.5 }}>
              Only the first {environments.length} environments are shown.
            </FormHelperText>
          )}

          <TextField
            select
            label="Test Phase (optional)"
            fullWidth
            value={phaseId}
            onChange={(e) => handlePhaseChange(e.target.value)}
          >
            <MenuItem value="">None</MenuItem>
            {phases.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label="Booking Type"
            required
            fullWidth
            value={bookingTypeId}
            onChange={(e) => setBookingTypeId(Number(e.target.value))}
          >
            {bookingTypes.map((bt) => (
              <MenuItem key={bt.id} value={bt.id}>
                {bt.name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            label="Purpose"
            required
            fullWidth
            value={projectName}
            onChange={(e) => setProjectName(e.target.value)}
          />

          <TextField
            label="Start Date"
            type="date"
            required
            fullWidth
            InputLabelProps={{ shrink: true }}
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />

          <TextField
            label="End Date"
            type="date"
            required
            fullWidth
            InputLabelProps={{ shrink: true }}
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={!canSubmit || submitting}
          onClick={handleSubmit}
        >
          {submitting ? 'Adding…' : 'Add Booking'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
