/**
 * AddPhaseBookingDialog — create a booking linked to a release phase.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchEnvironments } from '../../store/environmentSlice';
import { releaseService } from '../../services/releaseService';
import { bookingLifecycleService } from '../../services/bookingLifecycleService';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { TestPhaseResponse } from '../../types/release';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  phases: TestPhaseResponse[];
  onCreated: () => void;
}

export default function AddPhaseBookingDialog({
  open,
  onClose,
  releaseId,
  phases,
  onCreated,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const environments = useSelector((s: RootState) => s.environment.environments);

  const [bookingTypes, setBookingTypes] = useState<BookingTypeRecord[]>([]);
  const [envId, setEnvId] = useState<number | ''>('');
  const [phaseId, setPhaseId] = useState<number | ''>('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [projectName, setProjectName] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    dispatch(fetchEnvironments());
    bookingLifecycleService
      .listBookingTypes()
      .then(setBookingTypes)
      .catch(() => setBookingTypes([]));
  }, [dispatch]);

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

  const handleSubmit = async () => {
    if (!envId || !bookingTypeId || !projectName || !startDate || !endDate) return;
    setSubmitting(true);
    try {
      await releaseService.bookForPhase(releaseId, {
        environment_id: envId as number,
        project_name: projectName,
        start_date: new Date(startDate).toISOString(),
        end_date: new Date(endDate).toISOString(),
        booking_type_id: bookingTypeId as number,
        test_phase_id: phaseId !== '' ? (phaseId as number) : undefined,
      });
      snackbar.success('Booking created');
      resetForm();
      onCreated();
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create booking');
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

          <TextField
            select
            label="Test Phase (optional)"
            fullWidth
            value={phaseId}
            onChange={(e) =>
              setPhaseId(e.target.value === '' ? '' : Number(e.target.value))
            }
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
            label="Project Name"
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
