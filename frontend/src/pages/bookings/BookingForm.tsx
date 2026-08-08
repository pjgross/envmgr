import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Autocomplete,
  Box,
  Chip,
  FormControlLabel,
  FormHelperText,
  MenuItem,
  Switch,
  TextField,
} from '@mui/material';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { useAllProjects } from '../../hooks/useAllProjects';
import { useAllEnvironmentGroups } from '../../hooks/useAllEnvironmentGroups';
import { fetchDefinitions } from '../../store/customFieldSlice';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  selectBookingTemplates,
} from '../../store/bookingLifecycleSlice';
import { fetchUsers } from '../../store/tenantAdminSlice';
import { bookingRequestService } from '../../services/bookingRequestService';
import { createBookingRequest } from '../../store/bookingRequestSlice';
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

const baseSchema = z.object({
  envIds: z.array(z.number()),
  // A group expands to its current live members server-side — never
  // client-side, or membership would freeze at whatever the browser last
  // fetched and duplicate a rule the server owns. Picking a group alone must
  // be a valid submission, so this is not `.min(1)`'d on its own; the
  // combined "at least one of envIds/groupIds" rule lives in the `refine`
  // below, spanning both fields.
  groupIds: z.array(z.number()),
  projectName: z.string().trim().min(1, 'Purpose is required'),
  // The linked Project, distinct from `projectName` above (free text, "Purpose").
  projectId: z.number().nullable(),
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

const schema = baseSchema.refine(
  (values) => values.envIds.length > 0 || values.groupIds.length > 0,
  {
    message: 'Select at least one environment or environment group',
    path: ['envIds'],
  }
);

type BookingFormValues = z.infer<typeof baseSchema>;

const buildDefaults = (envIds: number[]): BookingFormValues => ({
  envIds,
  groupIds: [],
  projectName: '',
  projectId: null,
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

  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page, so this picker (mounted from
  // both BookingList and BookingCalendar) would silently offer a subset.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );
  const { bookingTypes } = useSelector((s: RootState) => s.bookingLifecycle);
  const templates = useSelector(selectBookingTemplates);
  const allUsers = useSelector((s: RootState) => s.tenantAdmin.users);
  const allUsersTotal = useSelector((s: RootState) => s.tenantAdmin.usersTotal);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);
  // Archived projects must not be offered here — useAllProjects always
  // narrows to active ones, unlike ReleaseForm's edit mode, which has an
  // existing value to preserve. This form is create-only, so there is never
  // a stale already-selected project to keep visible. Not the shared
  // `project` slice: since BookingList renders this form's dialog
  // unconditionally, reading `state.project.projects` here would race
  // BookingList's own project-filter fetch over the same slice.
  const { projects, truncated: projectsTruncated } = useAllProjects();
  // Same "must not silently be a subset" reasoning as environments/projects
  // above — mirrors useAllProjects, `is_active: true`-scoped, shared-fetch,
  // truncation-honest.
  const { groups, truncated: groupsTruncated } = useAllEnvironmentGroups();

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
      // Always sent, even empty — the server accepts an empty environment_ids
      // as long as environment_group_ids supplies at least one group; the
      // combined-empty case is a 400 from the service, not client-enforced
      // here beyond the refine above.
      environment_ids: values.envIds,
      // Group ids only — NEVER expand a group's members into environment_ids
      // here. This picker has no member list to expand from in the first
      // place (EnvironmentGroupResponse carries member_count, not member
      // ids), and expanding client-side would freeze membership at whatever
      // was last fetched and duplicate a rule the server owns: it resolves
      // each group to its *current* live members at booking time.
      ...(values.groupIds.length > 0 ? { environment_group_ids: values.groupIds } : {}),
      project_name: values.projectName.trim(),
      // Omitted entirely, not sent as null, when no project is chosen —
      // distinct from project_name (the free-text Purpose) above.
      ...(values.projectId != null ? { project_id: values.projectId } : {}),
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

    // Dispatched through the thunk (not a bare bookingRequestService.create
    // call) so a refusal — most notably the backend's overlap message naming
    // the colliding group(s) by name — is readable from `result.payload`.
    // RTK's default error serialisation drops `response.data.detail`, and a
    // real AxiosError's `.message` is only the generic HTTP-status text; see
    // the comment on `createBookingRequest` in bookingRequestSlice.
    const result = await dispatch(createBookingRequest(payload));
    if (createBookingRequest.rejected.match(result)) {
      snackbar.error(result.payload ?? 'Failed to create booking request');
      return;
    }

    const response = result.payload;
    // Not dispatch(fetchBookings()): the slice this once refreshed now
    // means "the current server-paged/filtered/sorted view" (BookingList)
    // or is bypassed entirely (BookingCalendar has its own fetch). A bare
    // unparameterised dispatch would clobber either with the endpoint's
    // default page-1, unfiltered, default-sort response. The caller knows
    // which refresh is correct for its own state.
    onCreated?.();
    const firstBookingId = response.request.bookings[0]?.id;
    snackbar.success('Booking created');

    // Usage-agreement gaps (A3) — ONE warning per gap, never a single "some
    // bookings have gaps" summary: a request can span several environments and
    // the user needs to know WHICH ones to get an agreement for.
    //
    // The server's message is shown verbatim and deliberately not re-worded
    // here: `agreement_gap_service` names the project and the environment in
    // it and never falls back to an id, and a second wording assembled in the
    // browser is a second answer to the same question — the divergence A1
    // produced by writing a count and a list separately.
    //
    // Iterated over `agreement_gaps` itself rather than over
    // `request.bookings`, so a gap for a booking missing from that list is
    // still surfaced rather than silently dropped. Keys are booking ids, so
    // the order is ascending booking id — deterministic, which the response's
    // own list order is not guaranteed to be.
    //
    // A3 WARNS: this runs AFTER the success path above, changes nothing about
    // it, and holds nothing open. The persistent home for the warning is the
    // booking's own page, which the navigation below lands on.
    for (const message of Object.values(response.agreement_gaps ?? {})) {
      snackbar.warning(message);
    }

    handleClose();
    if (firstBookingId) {
      navigate(`/bookings/${firstBookingId}`);
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
              {environmentsTruncated && (
                <FormHelperText>Only the first {environments.length} environments are shown.</FormHelperText>
              )}
              {fieldState.error?.message && (
                <Box sx={{ color: 'error.main', fontSize: 12, mt: 0.5 }}>
                  {fieldState.error.message}
                </Box>
              )}
            </Box>
          )}
        />

        {/* Environment groups (optional) — booking a group is not shorthand
            for hand-picking its current members: the whole point is that the
            server resolves the group to its live membership at booking time,
            not to a snapshot the browser fetched, and the resulting bookings
            are approved or rejected together as one unit. */}
        <Controller
          control={control}
          name="groupIds"
          render={({ field }) => {
            const selected = groups.filter((g) => field.value.includes(g.id));
            return (
              <Box>
                <Autocomplete
                  multiple
                  size="small"
                  options={groups}
                  getOptionLabel={(g) => g.name}
                  value={selected}
                  onChange={(_, next) => field.onChange(next.map((g) => g.id))}
                  isOptionEqualToValue={(o, v) => o.id === v.id}
                  renderTags={(vals, getTagProps) =>
                    vals.map((v, idx) => (
                      <Chip label={v.name} size="small" {...getTagProps({ index: idx })} key={v.id} />
                    ))
                  }
                  renderInput={(params) => <TextField {...params} label="Environment groups (optional)" />}
                />
                <FormHelperText>
                  Booking a group books all of its current environments; they will be approved or
                  rejected together.
                </FormHelperText>
                {groupsTruncated && (
                  <FormHelperText>Only the first {groups.length} environment groups are shown.</FormHelperText>
                )}
              </Box>
            );
          }}
        />

        {/* Project (optional) — the linked Project, distinct from the free-text
            Purpose field below. Sourced from active projects only; this form
            is create-only, so there's never a stale archived value to preserve. */}
        <Controller
          control={control}
          name="projectId"
          render={({ field }) => (
            <Autocomplete
              options={projects}
              getOptionLabel={(p) => p.name}
              value={projects.find((p) => p.id === field.value) ?? null}
              onChange={(_, next) => field.onChange(next ? next.id : null)}
              isOptionEqualToValue={(o, v) => o.id === v.id}
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Project (optional)"
                  helperText={
                    projectsTruncated
                      ? `Only the first ${projects.length} projects are shown.`
                      : undefined
                  }
                />
              )}
            />
          )}
        />

        {/* Purpose (free text) */}
        <FormTextField<BookingFormValues>
          name="projectName"
          label="Purpose"
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
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Delegates (optional)"
                  // GET /tenant/users is capped. Because this list is then
                  // filtered to active users, the number of options bears no
                  // relation to the cap — so the count alone gives no hint
                  // that anyone is missing.
                  helperText={
                    allUsers.length < allUsersTotal
                      ? `Only the first ${allUsers.length} of ${allUsersTotal} users are available to choose from.`
                      : undefined
                  }
                />
              )}
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
