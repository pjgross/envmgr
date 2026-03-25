import { useState, useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormLabel,
  InputLabel,
  MenuItem,
  Radio,
  RadioGroup,
  Select,
  Snackbar,
  Alert,
  Switch,
  TextField,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { createBooking, fetchBookings } from '../../store/bookingSlice';
import type { BookingCreate, ContextTag } from '../../types/booking';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { fetchBookingTypes, fetchLifecycleTemplates } from '../../store/bookingLifecycleSlice';
import CustomFieldsSection from '../../components/CustomFieldsSection';

interface BookingFormProps {
  open: boolean;
  onClose: () => void;
  defaultEnvId?: number;
}

type RecurrenceFreq = 'none' | 'daily' | 'weekly' | 'monthly';
type EndCondition = 'count' | 'until';

function buildRrule(
  freq: RecurrenceFreq,
  endCondition: EndCondition,
  count: number,
  until: string
): string | undefined {
  if (freq === 'none') return undefined;
  const freqMap: Record<string, string> = {
    daily: 'DAILY',
    weekly: 'WEEKLY',
    monthly: 'MONTHLY',
  };
  const freqStr = freqMap[freq];
  if (endCondition === 'count') {
    return `FREQ=${freqStr};COUNT=${count}`;
  } else {
    // Convert "YYYY-MM-DD" to RFC 5545 UTC datetime (YYYYMMDDTHHMMSSZ)
    const untilStr = until.replace(/-/g, '') + 'T000000Z';
    return `FREQ=${freqStr};UNTIL=${untilStr}`;
  }
}

export default function BookingForm({ open, onClose, defaultEnvId }: BookingFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const environments = useSelector((state: RootState) => state.environment.environments);
  const { loading } = useSelector((state: RootState) => state.booking);
  const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? []);
  const { bookingTypes, templates } = useSelector((s: RootState) => s.bookingLifecycle);

  const [envId, setEnvId] = useState<number | ''>(defaultEnvId ?? '');
  const [projectName, setProjectName] = useState('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [notes, setNotes] = useState('');
  const [contextTag, setContextTag] = useState<ContextTag>('none');
  const [exclusiveUse, setExclusiveUse] = useState(false);

  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  // Recurrence state
  const [recurrenceFreq, setRecurrenceFreq] = useState<RecurrenceFreq>('none');
  const [endCondition, setEndCondition] = useState<EndCondition>('count');
  const [recurrenceCount, setRecurrenceCount] = useState(4);
  const [recurrenceUntil, setRecurrenceUntil] = useState('');

  useEffect(() => {
    dispatch(fetchDefinitions('booking'));
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
  }, [dispatch]);

  // Auto-select first active booking type once loaded
  useEffect(() => {
    if (!bookingTypeId && bookingTypes.length > 0) {
      setBookingTypeId(bookingTypes.find((bt) => bt.is_active)?.id ?? '');
    }
  }, [bookingTypes, bookingTypeId]);

  const visibleCustomFieldDefs = useMemo(() => {
    if (!bookingTypeId) return [];
    const bt = bookingTypes.find((t) => t.id === bookingTypeId);
    if (!bt) return [];
    const template = templates.find((t) => t.id === bt.lifecycle_template_id);
    if (!template) return [];
    const initialState = template.definition.states.find((s) => s.is_initial);
    if (!initialState) return [];
    const cfPerms = template.definition.field_permissions?.[initialState.key]?.custom_fields ?? {};
    const visibleKeys = new Set(Object.keys(cfPerms));
    return customFieldDefs.filter((d) => visibleKeys.has(d.field_key));
  }, [bookingTypeId, bookingTypes, templates, customFieldDefs]);

  // Feedback state
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'warning' | 'error' }>({
    open: false,
    message: '',
    severity: 'success',
  });
  const [conflictError, setConflictError] = useState<string | null>(null);

  const handleSubmit = async () => {
    if (!envId || !projectName || !startDate || !endDate) return;

    const rrule = buildRrule(recurrenceFreq, endCondition, recurrenceCount, recurrenceUntil);

    const payload: BookingCreate = {
      environment_id: envId as number,
      project_name: projectName,
      start_date: new Date(startDate).toISOString(),
      end_date: new Date(endDate).toISOString(),
      booking_type_id: bookingTypeId as number,
      exclusive_use: exclusiveUse,
      notes: notes || undefined,
      recurrence_rule: rrule,
      context_tag: contextTag,
      custom_fields: customFieldValues,
    };

    const result = await dispatch(createBooking(payload));

    if (createBooking.fulfilled.match(result)) {
      const warnings = result.payload.overlap_warnings;
      if (warnings.length > 0) {
        setSnackbar({
          open: true,
          message: `Booking created. ${warnings.length} existing booking(s) overlap (shared).`,
          severity: 'warning',
        });
      } else {
        setSnackbar({ open: true, message: 'Booking created successfully.', severity: 'success' });
      }
      dispatch(fetchBookings());
      handleClose();
    } else if (createBooking.rejected.match(result)) {
      // Try to parse conflict detail
      const errMsg = result.error.message ?? 'Failed to create booking';
      if (errMsg.includes('409') || errMsg.toLowerCase().includes('conflict')) {
        setConflictError('This time slot has an exclusive booking conflict. Please choose a different time.');
      } else {
        setSnackbar({ open: true, message: errMsg, severity: 'error' });
      }
    }
  };

  const handleClose = () => {
    setEnvId(defaultEnvId ?? '');
    setProjectName('');
    setBookingTypeId('');
    setExclusiveUse(false);
    setStartDate('');
    setEndDate('');
    setNotes('');
    setContextTag('none');
    setRecurrenceFreq('none');
    setEndCondition('count');
    setRecurrenceCount(4);
    setRecurrenceUntil('');
    setConflictError(null);
    setCustomFieldValues({});
    onClose();
  };

  return (
    <>
      <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
        <DialogTitle>New Booking</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
            Booking will be saved as <strong>Draft</strong>. Submit when ready for approval.
          </Alert>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            {/* Environment */}
            <FormControl fullWidth required>
              <InputLabel>Environment</InputLabel>
              <Select
                value={envId}
                label="Environment"
                onChange={(e) => setEnvId(e.target.value as number)}
              >
                {environments.map((env) => (
                  <MenuItem key={env.id} value={env.id}>
                    {env.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {/* Project Name */}
            <TextField
              label="Project Name"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              required
              fullWidth
            />

            {/* Booking Type */}
            <TextField
              select
              label="Booking Type"
              required
              value={bookingTypeId}
              onChange={(e) => setBookingTypeId(Number(e.target.value))}
              error={bookingTypes.length === 0}
              helperText={bookingTypes.length === 0 ? 'No booking types configured — contact your admin' : undefined}
              disabled={bookingTypes.length === 0}
              fullWidth
            >
              {bookingTypes.filter((bt) => bt.is_active).map((bt) => (
                <MenuItem key={bt.id} value={bt.id}>{bt.name}</MenuItem>
              ))}
            </TextField>

            {/* Exclusive Use */}
            <FormControlLabel
              control={
                <Switch
                  checked={exclusiveUse}
                  onChange={(e) => setExclusiveUse(e.target.checked)}
                />
              }
              label="Request exclusive use of environment"
            />

            {/* Start / End Date */}
            <TextField
              label="Start Date & Time"
              type="datetime-local"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              required
              fullWidth
            />
            <TextField
              label="End Date & Time"
              type="datetime-local"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
              required
              fullWidth
            />

            {/* Context Tag */}
            <FormControl fullWidth>
              <InputLabel>Context Tag</InputLabel>
              <Select
                value={contextTag}
                label="Context Tag"
                onChange={(e) => setContextTag(e.target.value as ContextTag)}
              >
                <MenuItem value="none">None</MenuItem>
                <MenuItem value="deployment">Deployment</MenuItem>
                <MenuItem value="regression">Regression</MenuItem>
              </Select>
            </FormControl>

            {/* Notes */}
            <TextField
              label="Notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              multiline
              rows={3}
              fullWidth
            />

            {/* Recurrence */}
            <Box>
              <FormControl fullWidth>
                <InputLabel>Recurrence</InputLabel>
                <Select
                  value={recurrenceFreq}
                  label="Recurrence"
                  onChange={(e) => setRecurrenceFreq(e.target.value as RecurrenceFreq)}
                >
                  <MenuItem value="none">None</MenuItem>
                  <MenuItem value="daily">Daily</MenuItem>
                  <MenuItem value="weekly">Weekly</MenuItem>
                  <MenuItem value="monthly">Monthly</MenuItem>
                </Select>
              </FormControl>

              <Collapse in={recurrenceFreq !== 'none'}>
                <Box sx={{ mt: 2, pl: 1, display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <FormControl>
                    <FormLabel>End Condition</FormLabel>
                    <RadioGroup
                      row
                      value={endCondition}
                      onChange={(e) => setEndCondition(e.target.value as EndCondition)}
                    >
                      <FormControlLabel value="count" control={<Radio />} label="After N occurrences" />
                      <FormControlLabel value="until" control={<Radio />} label="Until date" />
                    </RadioGroup>
                  </FormControl>

                  {endCondition === 'count' ? (
                    <TextField
                      label="Number of Occurrences"
                      type="number"
                      value={recurrenceCount}
                      onChange={(e) => setRecurrenceCount(parseInt(e.target.value) || 1)}
                      inputProps={{ min: 1, max: 100 }}
                      fullWidth
                    />
                  ) : (
                    <TextField
                      label="Until Date"
                      type="date"
                      value={recurrenceUntil}
                      onChange={(e) => setRecurrenceUntil(e.target.value)}
                      InputLabelProps={{ shrink: true }}
                      fullWidth
                    />
                  )}
                </Box>
              </Collapse>
            </Box>

            {/* Custom Fields */}
            <CustomFieldsSection
              definitions={visibleCustomFieldDefs}
              values={customFieldValues}
              onChange={setCustomFieldValues}
            />

            {/* Conflict error */}
            {conflictError && (
              <Alert severity="error" onClose={() => setConflictError(null)}>
                {conflictError}
              </Alert>
            )}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button
            onClick={handleSubmit}
            variant="contained"
            disabled={loading || !envId || !projectName || !startDate || !endDate || !bookingTypeId}
          >
            {loading ? 'Creating...' : 'Create Booking'}
          </Button>
        </DialogActions>
      </Dialog>

      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={snackbar.severity} onClose={() => setSnackbar((s) => ({ ...s, open: false }))}>
          {snackbar.message}
        </Alert>
      </Snackbar>
    </>
  );
}
