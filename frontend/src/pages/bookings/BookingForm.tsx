import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Autocomplete,
  Box,
  Chip,
  FormControlLabel,
  MenuItem,
  Switch,
  TextField,
} from '@mui/material';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { fetchDefinitions } from '../../store/customFieldSlice';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  selectBookingTemplates,
} from '../../store/bookingLifecycleSlice';
import { fetchUsers } from '../../store/tenantAdminSlice';
import { bookingRequestService } from '../../services/bookingRequestService';
import type { BookingRequestCreatePayload } from '../../types/bookingRequest';
import type { UserResponse } from '../../types';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import EnvironmentPicker from '../../components/bookings/EnvironmentPicker';
import FormDialog from '../../components/form/FormDialog';
import FormTextField from '../../components/form/FormTextField';
import FormSelect from '../../components/form/FormSelect';
import { useSnackbar } from '../../hooks/useSnackbar';

interface BookingFormProps {
  open: boolean;
  onClose: () => void;
  /** @deprecated use defaultEnvIds */
  defaultEnvId?: number;
  defaultEnvIds?: number[];
  /**
   * Called after a booking is successfully created. `BookingForm` is mounted
   * as a dialog child of both `BookingList` (server-paged/filtered/sorted)
   * and `BookingCalendar` (its own month fetch), and a bare
   * `dispatch(fetchBookings())` here would overwrite whichever slice/state
   * the parent actually owns with the endpoint's unfiltered page-1 default.
   * Each parent supplies its own correct refresh instead.
   */
  onCreated?: () => void;
}

const schema = z.object({
  envIds: z.array(z.number()).min(1, 'Select at least one environment'),
  projectName: z.string().trim().min(1, 'Project name is required'),
  // Validated at submit time as a non-null number via setError below.
  bookingTypeId: z.number().nullable(),
  startDate: z.string().min(1, 'Start date is required'),
  endDate: z.string().min(1, 'End date is required'),
  notes: z.string(),
  contextTag: z.enum(['none', 'deployment', 'regression']),
  exclusiveUse: z.boolean(),
  delegateUsers: z.array(z.any()),
  customFieldValues: z.record(z.string(), z.unknown()),
});

type BookingFormValues = z.infer<typeof schema>;

const buildDefaults = (envIds: number[]): BookingFormValues => ({
  envIds,
  projectName: '',
  bookingTypeId: null,
  startDate: '',
  endDate: '',
  notes: '',
  contextTag: 'none',
  exclusiveUse: false,
  delegateUsers: [],
  customFieldValues: {},
});

export default function BookingForm({
  open,
  onClose,
  defaultEnvId,
  defaultEnvIds,
  onCreated,
}: BookingFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const environments = useSelector((state: RootState) => state.environment.environments);
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );
  const { bookingTypes } = useSelector((s: RootState) => s.bookingLifecycle);
  const templates = useSelector(selectBookingTemplates);
  const allUsers = useSelector((s: RootState) => s.tenantAdmin.users);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const initialEnvIds = useMemo(() => {
    if (defaultEnvIds && defaultEnvIds.length > 0) return defaultEnvIds;
    if (defaultEnvId != null) return [defaultEnvId];
    return [];
  }, [defaultEnvIds, defaultEnvId]);

  const form = useForm<BookingFormValues>({
    resolver: zodResolver(schema),
    defaultValues: buildDefaults(initialEnvIds),
    mode: 'onSubmit',
  });
  const { control, reset, setValue, watch } = form;

  // Conflict preview state (not part of the form)
  const conflictDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [conflictWarnings, setConflictWarnings] = useState<
    Record<number, { env_name: string; count: number }>
  >({});

  useEffect(() => {
    dispatch(fetchDefinitions('booking'));
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates('booking'));
    dispatch(fetchUsers());
  }, [dispatch]);

  // Auto-select first active booking type once loaded
  const bookingTypeIdValue = watch('bookingTypeId');
  useEffect(() => {
    if (bookingTypeIdValue == null && bookingTypes.length > 0) {
      const firstActive = bookingTypes.find((bt) => bt.is_active);
      if (firstActive) setValue('bookingTypeId', firstActive.id, { shouldValidate: false });
    }
  }, [bookingTypes, bookingTypeIdValue, setValue]);

  // Reset form when dialog opens with new defaults
  useEffect(() => {
    if (open) {
      reset(buildDefaults(initialEnvIds));
      setConflictWarnings({});
    }
  }, [open, initialEnvIds, reset]);

  // Debounced conflict preview — watch only the fields that affect it
  const envIdsValue = useWatch({ control, name: 'envIds' });
  const startDateValue = useWatch({ control, name: 'startDate' });
  const endDateValue = useWatch({ control, name: 'endDate' });

  useEffect(() => {
    if (conflictDebounceRef.current) clearTimeout(conflictDebounceRef.current);

    if (envIdsValue.length === 0 || !startDateValue || !endDateValue) {
      setConflictWarnings({});
      return;
    }

    conflictDebounceRef.current = setTimeout(async () => {
      try {
        const result = await bookingRequestService.previewConflicts({
          environment_ids: envIdsValue,
          start_date: new Date(startDateValue).toISOString(),
          end_date: new Date(endDateValue).toISOString(),
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
  }, [envIdsValue, startDateValue, endDateValue, environments]);

  const visibleCustomFieldDefs = useMemo(() => {
    if (bookingTypeIdValue == null) return [];
    const bt = bookingTypes.find((t) => t.id === bookingTypeIdValue);
    if (!bt) return [];
    const template = templates.find((t) => t.id === bt.lifecycle_template_id);
    if (!template) return [];
    const initialState = template.definition.states.find((s) => s.is_initial);
    if (!initialState) return [];
    const cfPerms = template.definition.field_permissions?.[initialState.key]?.custom_fields ?? {};
    const visibleKeys = new Set(Object.keys(cfPerms));
    return customFieldDefs.filter((d) => visibleKeys.has(d.field_key));
  }, [bookingTypeIdValue, bookingTypes, templates, customFieldDefs]);

  const delegateCandidates = useMemo(
    () => allUsers.filter((u) => u.is_active && u.id !== currentUserId),
    [allUsers, currentUserId]
  );

  const handleClose = () => {
    reset(buildDefaults(initialEnvIds));
    setConflictWarnings({});
    onClose();
  };

  const onSubmit = async (values: BookingFormValues) => {
    if (values.bookingTypeId == null) {
      form.setError('bookingTypeId', {
        type: 'required',
        message: 'Booking type is required',
      });
      return;
    }
    const payload: BookingRequestCreatePayload = {
      environment_ids: values.envIds,
      project_name: values.projectName.trim(),
      start_date: new Date(values.startDate).toISOString(),
      end_date: new Date(values.endDate).toISOString(),
      booking_type_id: values.bookingTypeId,
      exclusive_use_requested: values.exclusiveUse,
      notes: values.notes || undefined,
      context_tag: values.contextTag,
      custom_fields: values.customFieldValues,
      delegate_user_ids:
        values.delegateUsers.length > 0
          ? (values.delegateUsers as UserResponse[]).map((u) => u.id)
          : undefined,
    };

    try {
      const response = await bookingRequestService.create(payload);
      // Not dispatch(fetchBookings()): the slice this once refreshed now
      // means "the current server-paged/filtered/sorted view" (BookingList)
      // or is bypassed entirely (BookingCalendar has its own fetch). A bare
      // unparameterised dispatch would clobber either with the endpoint's
      // default page-1, unfiltered, default-sort response. The caller knows
      // which refresh is correct for its own state.
      onCreated?.();
      const firstBookingId = response.request.bookings[0]?.id;
      snackbar.success('Booking created');
      handleClose();
      if (firstBookingId) {
        navigate(`/bookings/${firstBookingId}`);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to create booking request';
      snackbar.error(msg);
    }
  };

  const conflictEnvIds = Object.keys(conflictWarnings).map(Number);
  const hasConflicts = conflictEnvIds.length > 0;

  return (
    <FormDialog<BookingFormValues>
      open={open}
      onClose={handleClose}
      title="New Booking Request"
      form={form}
      onSubmit={onSubmit}
      submitLabel="Create Booking"
      submittingLabel="Creating..."
    >
      <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
        Booking will be saved as <strong>Draft</strong>. Submit when ready for approval.
      </Alert>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        {/* Environments */}
        <Controller
          control={control}
          name="envIds"
          render={({ field, fieldState }) => (
            <Box>
              <EnvironmentPicker
                environments={environments}
                value={field.value}
                onChange={field.onChange}
                label="Environments *"
              />
              {fieldState.error?.message && (
                <Box sx={{ color: 'error.main', fontSize: 12, mt: 0.5 }}>
                  {fieldState.error.message}
                </Box>
              )}
            </Box>
          )}
        />

        {/* Project Name */}
        <FormTextField<BookingFormValues>
          name="projectName"
          label="Project Name"
          required
          fullWidth
        />

        {/* Booking Type */}
        <FormSelect<BookingFormValues>
          name="bookingTypeId"
          label="Booking Type"
          required
          fullWidth
          disabled={bookingTypes.length === 0}
          helperText={
            bookingTypes.length === 0
              ? 'No booking types configured — contact your admin'
              : undefined
          }
        >
          {bookingTypes
            .filter((bt) => bt.is_active)
            .map((bt) => (
              <MenuItem key={bt.id} value={bt.id}>
                {bt.name}
              </MenuItem>
            ))}
        </FormSelect>

        {/* Start / End Date */}
        <FormTextField<BookingFormValues>
          name="startDate"
          label="Start Date & Time"
          type="datetime-local"
          InputLabelProps={{ shrink: true }}
          required
          fullWidth
        />
        <FormTextField<BookingFormValues>
          name="endDate"
          label="End Date & Time"
          type="datetime-local"
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
                  <strong>{w.env_name}</strong> has {w.count} existing booking
                  {w.count !== 1 ? 's' : ''} overlapping this window. You can proceed; conflicts
                  will require acknowledgement after creation.
                </Alert>
              );
            })}
          </Box>
        )}

        {/* Context Tag */}
        <FormSelect<BookingFormValues> name="contextTag" label="Context Tag" fullWidth>
          <MenuItem value="none">None</MenuItem>
          <MenuItem value="deployment">Deployment</MenuItem>
          <MenuItem value="regression">Regression</MenuItem>
        </FormSelect>

        {/* Exclusive Use */}
        <Controller
          control={control}
          name="exclusiveUse"
          render={({ field }) => (
            <FormControlLabel
              control={
                <Switch checked={field.value} onChange={(e) => field.onChange(e.target.checked)} />
              }
              label="Exclusive use requested"
            />
          )}
        />

        {/* Delegate Users */}
        <Controller
          control={control}
          name="delegateUsers"
          render={({ field }) => (
            <Autocomplete
              multiple
              options={delegateCandidates}
              getOptionLabel={(u) => `${u.username} (${u.email})`}
              value={field.value as UserResponse[]}
              onChange={(_, next) => field.onChange(next)}
              isOptionEqualToValue={(o, v) => o.id === v.id}
              renderTags={(vals, getTagProps) =>
                vals.map((u, idx) => (
                  <Chip
                    label={u.username}
                    size="small"
                    {...getTagProps({ index: idx })}
                    key={u.id}
                  />
                ))
              }
              renderInput={(params) => <TextField {...params} label="Delegates (optional)" />}
            />
          )}
        />

        {/* Notes */}
        <FormTextField<BookingFormValues> name="notes" label="Notes" multiline rows={3} fullWidth />

        {/* Custom Fields */}
        <Controller
          control={control}
          name="customFieldValues"
          render={({ field }) => (
            <CustomFieldsSection
              definitions={visibleCustomFieldDefs}
              values={field.value}
              onChange={field.onChange}
            />
          )}
        />
      </Box>
    </FormDialog>
  );
}
