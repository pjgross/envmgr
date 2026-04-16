import { useState, useEffect, useMemo, useRef } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Alert,
  Switch,
  TextField,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import { fetchBookings } from '../../store/bookingSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { fetchBookingTypes, fetchLifecycleTemplates } from '../../store/bookingLifecycleSlice';
import { fetchUsers } from '../../store/tenantAdminSlice';
import { bookingRequestService } from '../../services/bookingRequestService';
import type { BookingRequestCreatePayload } from '../../types/bookingRequest';
import type { ContextTag } from '../../types/booking';
import type { UserResponse } from '../../types';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import EnvironmentPicker from '../../components/bookings/EnvironmentPicker';

interface BookingFormProps {
  open: boolean;
  onClose: () => void;
  /** @deprecated use defaultEnvIds */
  defaultEnvId?: number;
  defaultEnvIds?: number[];
}

export default function BookingForm({ open, onClose, defaultEnvId, defaultEnvIds }: BookingFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const environments = useSelector((state: RootState) => state.environment.environments);
  const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['booking'] ?? []);
  const { bookingTypes, templates } = useSelector((s: RootState) => s.bookingLifecycle);
  const allUsers = useSelector((s: RootState) => s.tenantAdmin.users);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  // Derive initial env ids from props
  const initialEnvIds = useMemo(() => {
    if (defaultEnvIds && defaultEnvIds.length > 0) return defaultEnvIds;
    if (defaultEnvId != null) return [defaultEnvId];
    return [];
  }, [defaultEnvIds, defaultEnvId]);

  const [envIds, setEnvIds] = useState<number[]>(initialEnvIds);
  const [projectName, setProjectName] = useState('');
  const [bookingTypeId, setBookingTypeId] = useState<number | ''>('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [notes, setNotes] = useState('');
  const [contextTag, setContextTag] = useState<ContextTag>('none');
  const [exclusiveUse, setExclusiveUse] = useState(false);
  const [delegateUsers, setDelegateUsers] = useState<UserResponse[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Conflict preview state
  const [conflictWarnings, setConflictWarnings] = useState<Record<number, { env_name: string; count: number }>>({});
  const conflictDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    dispatch(fetchDefinitions('booking'));
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
    dispatch(fetchUsers());
  }, [dispatch]);

  // Auto-select first active booking type once loaded
  useEffect(() => {
    if (!bookingTypeId && bookingTypes.length > 0) {
      setBookingTypeId(bookingTypes.find((bt) => bt.is_active)?.id ?? '');
    }
  }, [bookingTypes, bookingTypeId]);

  // Reset envIds when dialog opens with new defaults
  useEffect(() => {
    if (open) {
      setEnvIds(initialEnvIds);
    }
  }, [open, initialEnvIds]);

  // Debounced conflict preview
  useEffect(() => {
    if (conflictDebounceRef.current) clearTimeout(conflictDebounceRef.current);

    if (envIds.length === 0 || !startDate || !endDate) {
      setConflictWarnings({});
      return;
    }

    conflictDebounceRef.current = setTimeout(async () => {
      try {
        const result = await bookingRequestService.previewConflicts({
          environment_ids: envIds,
          start_date: new Date(startDate).toISOString(),
          end_date: new Date(endDate).toISOString(),
        });
        const warnings: Record<number, { env_name: string; count: number }> = {};
        for (const [envIdStr, bookings] of Object.entries(result.conflicts)) {
          if (bookings.length > 0) {
            const envId = Number(envIdStr);
            const env = environments.find((e) => e.id === envId);
            warnings[envId] = {
              env_name: env?.name ?? `Environment ${envId}`,
              count: bookings.length,
            };
          }
        }
        setConflictWarnings(warnings);
      } catch {
        // Silently ignore preview errors — not critical
        setConflictWarnings({});
      }
    }, 400);

    return () => {
      if (conflictDebounceRef.current) clearTimeout(conflictDebounceRef.current);
    };
  }, [envIds, startDate, endDate, environments]);

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

  // Active users excluding current user
  const delegateCandidates = useMemo(
    () => allUsers.filter((u) => u.is_active && u.id !== currentUserId),
    [allUsers, currentUserId],
  );

  const handleSubmit = async () => {
    if (envIds.length === 0 || !projectName || !startDate || !endDate || !bookingTypeId) return;

    setSubmitting(true);
    setSubmitError(null);

    const payload: BookingRequestCreatePayload = {
      environment_ids: envIds,
      project_name: projectName,
      start_date: new Date(startDate).toISOString(),
      end_date: new Date(endDate).toISOString(),
      booking_type_id: bookingTypeId as number,
      exclusive_use_requested: exclusiveUse,
      notes: notes || undefined,
      context_tag: contextTag,
      custom_fields: customFieldValues,
      delegate_user_ids: delegateUsers.length > 0 ? delegateUsers.map((u) => u.id) : undefined,
    };

    try {
      const response = await bookingRequestService.create(payload);
      dispatch(fetchBookings());
      const firstBookingId = response.request.bookings[0]?.id;
      handleClose();
      if (firstBookingId) {
        navigate(`/bookings/${firstBookingId}`);
      }
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'Failed to create booking request';
      setSubmitError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setEnvIds(initialEnvIds);
    setProjectName('');
    setBookingTypeId('');
    setExclusiveUse(false);
    setStartDate('');
    setEndDate('');
    setNotes('');
    setContextTag('none');
    setDelegateUsers([]);
    setSubmitError(null);
    setConflictWarnings({});
    setCustomFieldValues({});
    onClose();
  };

  const conflictEnvIds = Object.keys(conflictWarnings).map(Number);
  const hasConflicts = conflictEnvIds.length > 0;

  const isSubmitDisabled =
    submitting || envIds.length === 0 || !projectName || !startDate || !endDate || !bookingTypeId;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>New Booking Request</DialogTitle>
      <DialogContent>
        <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
          Booking will be saved as <strong>Draft</strong>. Submit when ready for approval.
        </Alert>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {/* Environments */}
          <EnvironmentPicker
            environments={environments}
            value={envIds}
            onChange={setEnvIds}
            label="Environments *"
          />

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

          {/* Conflict preview */}
          {hasConflicts && (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {conflictEnvIds.map((eid) => {
                const w = conflictWarnings[eid];
                return (
                  <Alert key={eid} severity="warning">
                    <strong>{w.env_name}</strong> has {w.count} existing booking{w.count !== 1 ? 's' : ''} overlapping
                    this window. You can proceed; conflicts will require acknowledgement after creation.
                  </Alert>
                );
              })}
            </Box>
          )}

          {/* Context Tag */}
          <TextField
            select
            label="Context Tag"
            value={contextTag}
            onChange={(e) => setContextTag(e.target.value as ContextTag)}
            fullWidth
          >
            <MenuItem value="none">None</MenuItem>
            <MenuItem value="deployment">Deployment</MenuItem>
            <MenuItem value="regression">Regression</MenuItem>
          </TextField>

          {/* Exclusive Use */}
          <FormControlLabel
            control={
              <Switch
                checked={exclusiveUse}
                onChange={(e) => setExclusiveUse(e.target.checked)}
              />
            }
            label="Exclusive use requested"
          />

          {/* Delegate Users */}
          <Autocomplete
            multiple
            options={delegateCandidates}
            getOptionLabel={(u) => `${u.username} (${u.email})`}
            value={delegateUsers}
            onChange={(_, next) => setDelegateUsers(next)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderTags={(vals, getTagProps) =>
              vals.map((u, idx) => (
                <Chip label={u.username} size="small" {...getTagProps({ index: idx })} key={u.id} />
              ))
            }
            renderInput={(params) => <TextField {...params} label="Delegates (optional)" />}
          />

          {/* Notes */}
          <TextField
            label="Notes"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            multiline
            rows={3}
            fullWidth
          />

          {/* Custom Fields */}
          <CustomFieldsSection
            definitions={visibleCustomFieldDefs}
            values={customFieldValues}
            onChange={setCustomFieldValues}
          />

          {/* Submit error */}
          {submitError && (
            <Alert severity="error" onClose={() => setSubmitError(null)}>
              {submitError}
            </Alert>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={isSubmitDisabled}
        >
          {submitting ? 'Creating...' : 'Create Booking'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
