import { useEffect, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, FormControlLabel, MenuItem, Switch } from '@mui/material';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { fetchEnvironments } from '../../store/environmentSlice';
import { fetchEnvSubsystems } from '../../store/environmentSlice';
import {
  fetchLifecycleTemplates,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { createChangeRequest } from '../../store/changeRequestSlice';
import FormDialog from '../../components/form/FormDialog';
import FormTextField from '../../components/form/FormTextField';
import FormSelect from '../../components/form/FormSelect';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ChangeRequestCreatePayload, ChangeType } from '../../types/changeRequest';

interface ChangeRequestFormProps {
  open: boolean;
  onClose: () => void;
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
    environment_id: z.number().nullable(),
    subsystem_id: z.number().nullable(),
    scheduled_start: z.string().min(1, 'Scheduled start is required'),
    scheduled_end: z.string().min(1, 'Scheduled end is required'),
    has_outage: z.boolean(),
    outage_start: z.string(),
    outage_end: z.string(),
  })
  .refine((v) => v.lifecycle_id != null, {
    path: ['lifecycle_id'],
    message: 'Lifecycle is required',
  })
  .refine((v) => v.environment_id != null, {
    path: ['environment_id'],
    message: 'Environment is required',
  })
  .refine((v) => v.subsystem_id != null, {
    path: ['subsystem_id'],
    message: 'Subsystem is required',
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
  environment_id: null,
  subsystem_id: null,
  scheduled_start: '',
  scheduled_end: '',
  has_outage: false,
  outage_start: '',
  outage_end: '',
});

export default function ChangeRequestForm({ open, onClose }: ChangeRequestFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const environments = useSelector((s: RootState) => s.environment.environments);
  const envSubsystems = useSelector((s: RootState) => s.environment.envSubsystems);
  const lifecycles = useSelector(selectTemplatesForEntity('change_request'));

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: buildDefaults(),
    mode: 'onSubmit',
  });
  const { control, watch, setValue, reset } = form;

  const environmentId = watch('environment_id');
  const hasOutage = watch('has_outage');

  useEffect(() => {
    dispatch(fetchEnvironments());
    dispatch(fetchLifecycleTemplates('change_request'));
  }, [dispatch]);

  // Auto-pick the default CR lifecycle on first open
  useEffect(() => {
    if (!open) return;
    const defaultTpl = lifecycles.find((t) => t.is_default) ?? lifecycles[0];
    if (defaultTpl && form.getValues('lifecycle_id') == null) {
      setValue('lifecycle_id', defaultTpl.id);
    }
  }, [open, lifecycles, setValue, form]);

  // When the environment changes, refresh its subsystems and clear any stale pick.
  useEffect(() => {
    if (environmentId != null) {
      dispatch(fetchEnvSubsystems(environmentId));
      setValue('subsystem_id', null);
    }
  }, [environmentId, dispatch, setValue]);

  const subsystemOptions = useMemo(
    () =>
      envSubsystems.map((s) => ({
        id: s.subsystem_id,
        label: `${s.system_name} / ${s.subsystem_name}`,
      })),
    [envSubsystems]
  );

  const handleClose = () => {
    reset(buildDefaults());
    onClose();
  };

  const onSubmit = async (values: FormValues) => {
    const payload: ChangeRequestCreatePayload = {
      title: values.title.trim(),
      description: values.description || null,
      change_type: values.change_type,
      lifecycle_id: values.lifecycle_id as number,
      environment_id: values.environment_id as number,
      subsystem_id: values.subsystem_id as number,
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
    };

    try {
      const action = await dispatch(createChangeRequest(payload));
      if ('error' in action) {
        throw new Error(action.error.message ?? 'Failed to create change request');
      }
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
    >
      <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
        Change requests follow the <strong>Simple Approval</strong> or
        <strong> Emergency</strong> lifecycle — pick the one that matches the urgency of
        this change.
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

        <FormSelect<FormValues> name="environment_id" label="Environment" required fullWidth>
          {environments.map((e) => (
            <MenuItem key={e.id} value={e.id}>
              {e.name}
            </MenuItem>
          ))}
        </FormSelect>

        <FormSelect<FormValues>
          name="subsystem_id"
          label="Subsystem"
          required
          fullWidth
          disabled={environmentId == null}
          helperText={
            environmentId == null
              ? 'Pick an environment first'
              : subsystemOptions.length === 0
                ? 'This environment has no subsystems configured'
                : undefined
          }
        >
          {subsystemOptions.map((s) => (
            <MenuItem key={s.id} value={s.id}>
              {s.label}
            </MenuItem>
          ))}
        </FormSelect>

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
