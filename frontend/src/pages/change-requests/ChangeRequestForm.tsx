import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Autocomplete,
  Box,
  Chip,
  CircularProgress,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { Controller, useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { fetchEnvSubsystems } from '../../store/environmentSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { useAllHosts } from '../../hooks/useAllHosts';
import {
  fetchLifecycleTemplates,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { createChangeRequest } from '../../store/changeRequestSlice';
import FormDialog from '../../components/form/FormDialog';
import FormTextField from '../../components/form/FormTextField';
import FormSelect from '../../components/form/FormSelect';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import BookingScheduleGantt from '../../components/BookingScheduleGantt';
import { useSnackbar } from '../../hooks/useSnackbar';
import { changeRequestService } from '../../services/changeRequestService';
import { infrastructureComponentService } from '../../services/infrastructureComponentService';
import type {
  ChangeRequestCreatePayload,
  ChangeType,
  OutageConflictEnvironment,
} from '../../types/changeRequest';
import type { HostImpactEnvironment } from '../../types/infrastructureComponent';

interface ChangeRequestFormProps {
  open: boolean;
  onClose: () => void;
  /**
   * Called after a change request is successfully created. `ChangeRequestForm`
   * is mounted as a dialog child of `ChangeRequestList`, which is now
   * server-paged/filtered/sorted; `state.list` no longer means "every change
   * request" so the slice no longer splices the new row in (see
   * changeRequestSlice's comment on createChangeRequest.fulfilled). The
   * parent re-issues its current query instead.
   */
  onCreated?: () => void;
}

const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'configuration', label: 'Configuration' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'code_deployment', label: 'Code Deployment' },
];

const schema = z
  .object({
    title: z.string().trim().min(1, 'Title is required'),
    description: z.string(),
    change_type: z.enum(['configuration', 'infrastructure', 'code_deployment']),
    lifecycle_id: z.number().nullable(),
    environment_ids: z.array(z.number()),
    host_ids: z.array(z.number()),
    subsystem_id: z.number().nullable(),
    scheduled_start: z.string().min(1, 'Scheduled start is required'),
    scheduled_end: z.string().min(1, 'Scheduled end is required'),
    has_outage: z.boolean(),
    outage_start: z.string(),
    outage_end: z.string(),
    custom_field_values: z.record(z.string(), z.unknown()),
  })
  .refine((v) => v.lifecycle_id != null, {
    path: ['lifecycle_id'],
    message: 'Lifecycle is required',
  })
  .refine((v) => v.environment_ids.length > 0 || v.host_ids.length > 0, {
    path: ['environment_ids'],
    message: 'Select at least one environment or host',
  })
  .refine((v) => new Date(v.scheduled_end) > new Date(v.scheduled_start), {
    path: ['scheduled_end'],
    message: 'Scheduled end must be after start',
  })
  .refine((v) => !v.has_outage || (!!v.outage_start && !!v.outage_end), {
    path: ['outage_start'],
    message: 'Outage start + end required when outage is flagged',
  })
  .refine(
    (v) => !v.has_outage || !v.outage_start || !v.outage_end
      || new Date(v.outage_end) > new Date(v.outage_start),
    { path: ['outage_end'], message: 'Outage end must be after outage start' }
  );

type FormValues = z.infer<typeof schema>;

const buildDefaults = (): FormValues => ({
  title: '',
  description: '',
  change_type: 'configuration',
  lifecycle_id: null,
  environment_ids: [],
  host_ids: [],
  subsystem_id: null,
  scheduled_start: '',
  scheduled_end: '',
  has_outage: false,
  outage_start: '',
  outage_end: '',
  custom_field_values: {},
});

export default function ChangeRequestForm({ open, onClose, onCreated }: ChangeRequestFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page, so the environment picker
  // below would silently offer a subset.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();
  const envSubsystems = useSelector((s: RootState) => s.environment.envSubsystems);
  // Not the shared component slice: since the C3 conversion (a later task)
  // it will become InfrastructureComponentList's current filtered page, so
  // the host picker below would silently offer a subset.
  const { hosts, truncated: hostsTruncated } = useAllHosts();
  const lifecycles = useSelector(selectTemplatesForEntity('change_request'));
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['change_request'] ?? []
  );

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: buildDefaults(),
    mode: 'onSubmit',
  });
  const { control, watch, setValue, reset } = form;

  const environmentIds = watch('environment_ids');
  const hostIds = watch('host_ids');
  const hasOutage = watch('has_outage');
  const scheduledStartStr = watch('scheduled_start');
  const scheduledEndStr = watch('scheduled_end');
  const outageStartStr = watch('outage_start');
  const outageEndStr = watch('outage_end');

  const [outageConflicts, setOutageConflicts] = useState<OutageConflictEnvironment[]>([]);
  const [derivedEnvs, setDerivedEnvs] = useState<{ id: number; name: string }[]>([]);
  const [hostImpact, setHostImpact] = useState<HostImpactEnvironment[]>([]);
  const [hostImpactLoading, setHostImpactLoading] = useState(false);
  const hostImpactDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const outageDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const previewEnvIds = useWatch({ control, name: 'environment_ids' });
  const previewHostIds = useWatch({ control, name: 'host_ids' });
  const previewStart = useWatch({ control, name: 'outage_start' });
  const previewEnd = useWatch({ control, name: 'outage_end' });
  const previewHasOutage = useWatch({ control, name: 'has_outage' });

  useEffect(() => {
    dispatch(fetchLifecycleTemplates('change_request'));
    dispatch(fetchDefinitions('change_request'));
  }, [dispatch]);

  useEffect(() => {
    if (!open) return;
    const defaultTpl = lifecycles.find((t) => t.is_default) ?? lifecycles[0];
    if (defaultTpl && form.getValues('lifecycle_id') == null) {
      setValue('lifecycle_id', defaultTpl.id);
    }
  }, [open, lifecycles, setValue, form]);

  // When environment selection is exactly one, fetch its subsystems for the optional picker
  const singleEnvId = environmentIds.length === 1 && hostIds.length === 0
    ? environmentIds[0]
    : null;
  useEffect(() => {
    if (singleEnvId != null) {
      dispatch(fetchEnvSubsystems(singleEnvId));
    }
    setValue('subsystem_id', null);
  }, [singleEnvId, dispatch, setValue]);

  // Host-impact panel: whenever selected hosts change, fetch the readonly
  // environment-and-subsystem breakdown so the env manager sees what's affected.
  useEffect(() => {
    if (hostImpactDebounceRef.current) clearTimeout(hostImpactDebounceRef.current);
    if (!hostIds || hostIds.length === 0) {
      setHostImpact([]);
      setHostImpactLoading(false);
      return;
    }
    setHostImpactLoading(true);
    hostImpactDebounceRef.current = setTimeout(async () => {
      try {
        const result = await infrastructureComponentService.hostImpact(hostIds);
        setHostImpact(result.environments);
      } catch {
        setHostImpact([]);
      } finally {
        setHostImpactLoading(false);
      }
    }, 300);
    return () => {
      if (hostImpactDebounceRef.current) clearTimeout(hostImpactDebounceRef.current);
    };
  }, [hostIds]);

  useEffect(() => {
    if (outageDebounceRef.current) clearTimeout(outageDebounceRef.current);
    const hasTargets =
      (previewEnvIds && previewEnvIds.length > 0) ||
      (previewHostIds && previewHostIds.length > 0);
    if (!previewHasOutage || !hasTargets || !previewStart || !previewEnd) {
      setOutageConflicts([]);
      setDerivedEnvs([]);
      return;
    }
    outageDebounceRef.current = setTimeout(async () => {
      try {
        const result = await changeRequestService.previewOutageConflicts({
          environment_ids: previewEnvIds,
          host_ids: previewHostIds,
          outage_start: new Date(previewStart).toISOString(),
          outage_end: new Date(previewEnd).toISOString(),
        });
        setOutageConflicts(result.environments);
        setDerivedEnvs(result.derived_environments);
      } catch {
        setOutageConflicts([]);
        setDerivedEnvs([]);
      }
    }, 400);
    return () => {
      if (outageDebounceRef.current) clearTimeout(outageDebounceRef.current);
    };
  }, [previewHasOutage, previewEnvIds, previewHostIds, previewStart, previewEnd]);

  const subsystemOptions = useMemo(
    () =>
      envSubsystems.map((s) => ({
        id: s.subsystem_id,
        label: `${s.system_name} / ${s.subsystem_name}`,
      })),
    [envSubsystems]
  );

  const envById = useMemo(() => new Map(environments.map((e) => [e.id, e])), [environments]);
  const hostById = useMemo(() => new Map(hosts.map((h) => [h.id, h])), [hosts]);

  const effectiveEnvs = useMemo(() => {
    const map = new Map<number, string>();
    for (const id of environmentIds) {
      const e = envById.get(id);
      if (e) map.set(id, e.name);
    }
    for (const env of hostImpact) {
      if (!map.has(env.environment_id)) {
        map.set(env.environment_id, env.environment_name);
      }
    }
    return Array.from(map, ([id, name]) => ({ id, name }));
  }, [environmentIds, envById, hostImpact]);

  const parseLocal = (s: string): Date | null => {
    if (!s) return null;
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  };

  const totalConflicts = outageConflicts.reduce((acc, e) => acc + e.conflicts.length, 0);

  const handleClose = () => {
    reset(buildDefaults());
    setOutageConflicts([]);
    setDerivedEnvs([]);
    onClose();
  };

  const onSubmit = async (values: FormValues) => {
    const payload: ChangeRequestCreatePayload = {
      title: values.title.trim(),
      description: values.description || null,
      change_type: values.change_type,
      lifecycle_id: values.lifecycle_id as number,
      environment_ids: values.environment_ids,
      host_ids: values.host_ids,
      subsystem_id: values.subsystem_id,
      scheduled_start: new Date(values.scheduled_start).toISOString(),
      scheduled_end: new Date(values.scheduled_end).toISOString(),
      has_outage: values.has_outage,
      outage_start:
        values.has_outage && values.outage_start
          ? new Date(values.outage_start).toISOString()
          : null,
      outage_end:
        values.has_outage && values.outage_end
          ? new Date(values.outage_end).toISOString()
          : null,
      custom_fields:
        Object.keys(values.custom_field_values).length > 0
          ? values.custom_field_values
          : null,
    };

    try {
      const action = await dispatch(createChangeRequest(payload));
      if ('error' in action) {
        throw new Error(action.error.message ?? 'Failed to create change request');
      }
      // Not a bare dispatch(fetchChangeRequests()): ChangeRequestList's
      // `state.list` is server-paged/filtered/sorted now, and the slice no
      // longer splices the new row in itself. The parent knows which
      // page/sort/filter query is current; re-issue it via onCreated.
      onCreated?.();
      snackbar.success('Change request created');
      const id = (action.payload as { id: number }).id;
      handleClose();
      navigate(`/change-requests/${id}`);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create change request');
    }
  };

  return (
    <FormDialog<FormValues>
      open={open}
      onClose={handleClose}
      title="New Change Request"
      form={form}
      onSubmit={onSubmit}
      submitLabel="Create Change Request"
      submittingLabel="Creating..."
      maxWidth="lg"
    >
      <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
        A change request must target at least one environment or host. Host-scoped
        changes automatically surface every environment whose subsystems run on that host.
      </Alert>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
        <FormTextField<FormValues> name="title" label="Title" required fullWidth />

        <FormSelect<FormValues> name="change_type" label="Change Type" required fullWidth>
          {CHANGE_TYPES.map((t) => (
            <MenuItem key={t.value} value={t.value}>
              {t.label}
            </MenuItem>
          ))}
        </FormSelect>

        <FormSelect<FormValues> name="lifecycle_id" label="Lifecycle" required fullWidth>
          {lifecycles.map((t) => (
            <MenuItem key={t.id} value={t.id}>
              {t.name}
              {t.is_default ? ' (default)' : ''}
            </MenuItem>
          ))}
        </FormSelect>

        <Controller
          control={control}
          name="environment_ids"
          render={({ field, fieldState }) => (
            <Autocomplete
              multiple
              options={environments}
              value={field.value.map((id) => envById.get(id)).filter(Boolean) as typeof environments}
              onChange={(_, v) => field.onChange(v.map((e) => e.id))}
              getOptionLabel={(e) => e.name}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              renderTags={(value, getTagProps) =>
                value.map((opt, index) => (
                  <Chip size="small" label={opt.name} {...getTagProps({ index })} key={opt.id} />
                ))
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Environments"
                  placeholder="Select one or more environments"
                  error={!!fieldState.error}
                  helperText={
                    fieldState.error?.message ??
                    (environmentsTruncated
                      ? `Only the first ${environments.length} environments are shown.`
                      : undefined)
                  }
                />
              )}
            />
          )}
        />

        <Controller
          control={control}
          name="host_ids"
          render={({ field }) => (
            <Autocomplete
              multiple
              options={hosts}
              value={field.value.map((id) => hostById.get(id)).filter(Boolean) as typeof hosts}
              onChange={(_, v) => field.onChange(v.map((h) => h.id))}
              getOptionLabel={(h) => `${h.name} (${h.component_type})`}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              renderTags={(value, getTagProps) =>
                value.map((opt, index) => (
                  <Chip size="small" label={opt.name} {...getTagProps({ index })} key={opt.id} />
                ))
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Hosts"
                  placeholder="Select one or more hosts"
                  helperText={
                    hostsTruncated
                      ? `Only the first ${hosts.length} hosts are shown.`
                      : 'Affected environments are derived automatically from host attachments'
                  }
                />
              )}
            />
          )}
        />

        {hostIds.length > 0 && (
          <Paper
            variant="outlined"
            sx={{ p: 2, bgcolor: 'action.hover' }}
          >
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
              <Typography variant="subtitle2">Host impact</Typography>
              <Typography variant="caption" color="text.secondary">
                (readonly)
              </Typography>
              {hostImpactLoading && <CircularProgress size={14} sx={{ ml: 0.5 }} />}
            </Box>
            {!hostImpactLoading && hostImpact.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No subsystems are currently deployed on the selected host
                {hostIds.length === 1 ? '' : 's'}. No environments will be impacted.
              </Typography>
            ) : (
              <Stack spacing={1.5}>
                {hostImpact.map((env) => (
                  <Box key={env.environment_id}>
                    <Typography variant="body2" fontWeight="medium">
                      {env.environment_name}
                      <Typography
                        component="span"
                        variant="caption"
                        color="text.secondary"
                        sx={{ ml: 1 }}
                      >
                        {env.subsystems.length} subsystem
                        {env.subsystems.length === 1 ? '' : 's'} affected
                      </Typography>
                    </Typography>
                    <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2.5 }}>
                      {env.subsystems.map((sub) => (
                        <Box
                          component="li"
                          key={sub.subsystem_id}
                          sx={{ mb: 0.5 }}
                        >
                          <Typography variant="body2">
                            <strong>{sub.subsystem_name}</strong>
                            <Typography
                              component="span"
                              variant="caption"
                              color="text.secondary"
                              sx={{ ml: 0.5 }}
                            >
                              · {sub.system_name}
                            </Typography>
                            {sub.is_mocked && (
                              <Chip
                                size="small"
                                label="mock"
                                color="warning"
                                variant="outlined"
                                sx={{ ml: 1, height: 18 }}
                              />
                            )}
                          </Typography>
                          <Box
                            sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.25 }}
                          >
                            {sub.matches.map((m) => (
                              <Chip
                                key={`${sub.subsystem_id}-${m.host_id}`}
                                size="small"
                                variant="outlined"
                                label={
                                  m.role ? `${m.host_name} · ${m.role}` : m.host_name
                                }
                              />
                            ))}
                          </Box>
                        </Box>
                      ))}
                    </Box>
                  </Box>
                ))}
              </Stack>
            )}
          </Paper>
        )}

        {singleEnvId != null && (
          <FormSelect<FormValues>
            name="subsystem_id"
            label="Subsystem (optional)"
            fullWidth
            helperText={
              subsystemOptions.length === 0
                ? 'This environment has no subsystems configured'
                : 'Narrow the change to one subsystem in this environment'
            }
          >
            <MenuItem value="">
              <em>None (env-wide)</em>
            </MenuItem>
            {subsystemOptions.map((s) => (
              <MenuItem key={s.id} value={s.id}>
                {s.label}
              </MenuItem>
            ))}
          </FormSelect>
        )}

        <FormTextField<FormValues>
          name="scheduled_start"
          label="Scheduled Start"
          type="datetime-local"
          InputLabelProps={{ shrink: true }}
          required
          fullWidth
        />
        <FormTextField<FormValues>
          name="scheduled_end"
          label="Scheduled End"
          type="datetime-local"
          InputLabelProps={{ shrink: true }}
          required
          fullWidth
        />

        {effectiveEnvs.length > 0 ? (
          <BookingScheduleGantt
            envs={effectiveEnvs}
            scheduledStart={parseLocal(scheduledStartStr)}
            scheduledEnd={parseLocal(scheduledEndStr)}
            hasOutage={hasOutage}
            outageStart={parseLocal(outageStartStr)}
            outageEnd={parseLocal(outageEndStr)}
          />
        ) : (
          <Alert severity="info" variant="outlined">
            Select an environment or host above to see the booking schedule for the
            affected environments alongside the proposed change window.
          </Alert>
        )}

        <Controller
          control={control}
          name="has_outage"
          render={({ field }) => (
            <FormControlLabel
              control={
                <Switch
                  checked={field.value}
                  onChange={(e) => field.onChange(e.target.checked)}
                />
              }
              label="This change causes an outage"
            />
          )}
        />

        {hasOutage && (
          <>
            <FormTextField<FormValues>
              name="outage_start"
              label="Outage Start"
              type="datetime-local"
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <FormTextField<FormValues>
              name="outage_end"
              label="Outage End"
              type="datetime-local"
              InputLabelProps={{ shrink: true }}
              fullWidth
            />

            {derivedEnvs.length > 0 && (
              <Alert severity="info">
                The following environment
                {derivedEnvs.length === 1 ? ' is' : 's are'} affected via the selected
                host
                {previewHostIds.length === 1 ? '' : 's'}:{' '}
                <strong>{derivedEnvs.map((e) => e.name).join(', ')}</strong>.
              </Alert>
            )}

            {totalConflicts > 0 && (
              <Alert severity="warning">
                <Typography variant="body2" sx={{ fontWeight: 'medium' }}>
                  {totalConflicts} booking{totalConflicts === 1 ? '' : 's'} across{' '}
                  {outageConflicts.filter((e) => e.conflicts.length > 0).length} environment
                  {outageConflicts.filter((e) => e.conflicts.length > 0).length === 1
                    ? ''
                    : 's'}{' '}
                  overlap this outage window. You can proceed; affected teams will want to know.
                </Typography>
                {outageConflicts
                  .filter((e) => e.conflicts.length > 0)
                  .map((env) => (
                    <Box key={env.environment_id} sx={{ mt: 1 }}>
                      <Typography variant="caption" sx={{ fontWeight: 'medium' }}>
                        {env.environment_name}:
                      </Typography>
                      <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2 }}>
                        {env.conflicts.map((b) => (
                          <li key={b.id}>
                            <strong>{b.project_name}</strong> (
                            {new Date(b.start_date).toLocaleString()} –{' '}
                            {new Date(b.end_date).toLocaleString()})
                          </li>
                        ))}
                      </Box>
                    </Box>
                  ))}
              </Alert>
            )}
          </>
        )}

        <Controller
          control={control}
          name="custom_field_values"
          render={({ field }) => (
            <CustomFieldsSection
              definitions={customFieldDefs}
              values={field.value}
              onChange={field.onChange}
            />
          )}
        />

        <FormTextField<FormValues>
          name="description"
          label="Description"
          multiline
          rows={3}
          fullWidth
        />
      </Box>
    </FormDialog>
  );
}
