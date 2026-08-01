import { useEffect, useMemo, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
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
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { updateChangeRequest } from '../../store/changeRequestSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { fetchInfrastructureComponents } from '../../store/infrastructureComponentSlice';
import FormDialog from '../../components/form/FormDialog';
import FormTextField from '../../components/form/FormTextField';
import FormSelect from '../../components/form/FormSelect';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import { useSnackbar } from '../../hooks/useSnackbar';
import { infrastructureComponentService } from '../../services/infrastructureComponentService';
import BookingScheduleGantt from '../../components/BookingScheduleGantt';
import type {
  ChangeRequestDetailResponse,
  ChangeRequestUpdatePayload,
  ChangeType,
} from '../../types/changeRequest';
import type { HostImpactEnvironment } from '../../types/infrastructureComponent';

interface Props {
  open: boolean;
  onClose: () => void;
  changeRequest: ChangeRequestDetailResponse;
}

const CHANGE_TYPES: { value: ChangeType; label: string }[] = [
  { value: 'configuration', label: 'Configuration' },
  { value: 'infrastructure', label: 'Infrastructure' },
  { value: 'code_deployment', label: 'Code Deployment' },
];

// Converts an ISO string into the value shape datetime-local inputs expect
// (YYYY-MM-DDTHH:MM, no timezone). Drops seconds/ms and the trailing Z.
function isoToLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const schema = z
  .object({
    title: z.string().trim().min(1, 'Title is required'),
    description: z.string(),
    change_type: z.enum(['configuration', 'infrastructure', 'code_deployment']),
    environment_ids: z.array(z.number()),
    host_ids: z.array(z.number()),
    scheduled_start: z.string().min(1, 'Scheduled start is required'),
    scheduled_end: z.string().min(1, 'Scheduled end is required'),
    has_outage: z.boolean(),
    outage_start: z.string(),
    outage_end: z.string(),
    custom_field_values: z.record(z.string(), z.unknown()),
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

export default function ChangeRequestEditDialog({ open, onClose, changeRequest }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['change_request'] ?? []
  );
  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page, so the environment picker
  // below would silently offer a subset.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();
  const hosts = useSelector((s: RootState) => s.infrastructureComponent.components);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: changeRequest.title,
      description: changeRequest.description ?? '',
      change_type: changeRequest.change_type,
      environment_ids: changeRequest.environment_ids,
      host_ids: changeRequest.host_ids,
      scheduled_start: isoToLocalInput(changeRequest.scheduled_start),
      scheduled_end: isoToLocalInput(changeRequest.scheduled_end),
      has_outage: changeRequest.has_outage,
      outage_start: isoToLocalInput(changeRequest.outage_start),
      outage_end: isoToLocalInput(changeRequest.outage_end),
      custom_field_values: (changeRequest.custom_fields ?? {}) as Record<string, unknown>,
    },
    mode: 'onSubmit',
  });
  const { control, watch, reset } = form;

  const hasOutage = watch('has_outage');
  const hostIds = watch('host_ids');
  const environmentIds = watch('environment_ids');
  const scheduledStartStr = watch('scheduled_start');
  const scheduledEndStr = watch('scheduled_end');
  const outageStartStr = watch('outage_start');
  const outageEndStr = watch('outage_end');

  const parseLocal = (s: string): Date | null => {
    if (!s) return null;
    const d = new Date(s);
    return Number.isNaN(d.getTime()) ? null : d;
  };

  const [hostImpact, setHostImpact] = useState<HostImpactEnvironment[]>([]);
  const [hostImpactLoading, setHostImpactLoading] = useState(false);
  const hostImpactDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const effectiveEnvs = useMemo(() => {
    const envById = new Map(environments.map((e) => [e.id, e]));
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
  }, [environmentIds, environments, hostImpact]);

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
    dispatch(fetchDefinitions('change_request'));
    dispatch(fetchInfrastructureComponents());
  }, [dispatch]);

  useEffect(() => {
    if (!open) return;
    reset({
      title: changeRequest.title,
      description: changeRequest.description ?? '',
      change_type: changeRequest.change_type,
      environment_ids: changeRequest.environment_ids,
      host_ids: changeRequest.host_ids,
      scheduled_start: isoToLocalInput(changeRequest.scheduled_start),
      scheduled_end: isoToLocalInput(changeRequest.scheduled_end),
      has_outage: changeRequest.has_outage,
      outage_start: isoToLocalInput(changeRequest.outage_start),
      outage_end: isoToLocalInput(changeRequest.outage_end),
      custom_field_values: (changeRequest.custom_fields ?? {}) as Record<string, unknown>,
    });
  }, [open, changeRequest, reset]);

  const onSubmit = async (values: FormValues) => {
    const payload: ChangeRequestUpdatePayload = {
      title: values.title.trim(),
      description: values.description || null,
      change_type: values.change_type,
      environment_ids: values.environment_ids,
      host_ids: values.host_ids,
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
      const action = await dispatch(
        updateChangeRequest({ id: changeRequest.id, data: payload })
      );
      if ('error' in action) {
        throw new Error(action.error.message ?? 'Failed to update change request');
      }
      snackbar.success('Change request updated');
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to update change request');
    }
  };

  return (
    <FormDialog<FormValues>
      open={open}
      onClose={onClose}
      title="Edit Change Request"
      form={form}
      onSubmit={onSubmit}
      submitLabel="Save changes"
      submittingLabel="Saving..."
      maxWidth="lg"
    >
      <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
        Lifecycle and subsystem can't be changed after creation. You can adjust the
        environments and hosts this change targets.
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

        <Controller
          control={control}
          name="environment_ids"
          render={({ field, fieldState }) => (
            <Autocomplete
              multiple
              options={environments}
              value={
                field.value
                  .map((id) => environments.find((e) => e.id === id))
                  .filter(Boolean) as typeof environments
              }
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
              value={
                field.value
                  .map((id) => hosts.find((h) => h.id === id))
                  .filter(Boolean) as typeof hosts
              }
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
                  helperText="Affected envs derived automatically"
                />
              )}
            />
          )}
        />

        {hostIds.length > 0 && (
          <Paper variant="outlined" sx={{ p: 2, bgcolor: 'action.hover' }}>
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
                {hostIds.length === 1 ? '' : 's'}.
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
                        <Box component="li" key={sub.subsystem_id} sx={{ mb: 0.5 }}>
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
                                label={m.role ? `${m.host_name} · ${m.role}` : m.host_name}
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
              label="This change causes an environment outage"
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
