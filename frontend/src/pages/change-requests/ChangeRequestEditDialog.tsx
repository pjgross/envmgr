import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Alert, Box, FormControlLabel, MenuItem, Switch } from '@mui/material';
import { Controller, useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch, RootState } from '../../store';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { updateChangeRequest } from '../../store/changeRequestSlice';
import FormDialog from '../../components/form/FormDialog';
import FormTextField from '../../components/form/FormTextField';
import FormSelect from '../../components/form/FormSelect';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import { useSnackbar } from '../../hooks/useSnackbar';
import type {
  ChangeRequestDetailResponse,
  ChangeRequestUpdatePayload,
  ChangeType,
} from '../../types/changeRequest';

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
    scheduled_start: z.string().min(1, 'Scheduled start is required'),
    scheduled_end: z.string().min(1, 'Scheduled end is required'),
    has_outage: z.boolean(),
    outage_start: z.string(),
    outage_end: z.string(),
    custom_field_values: z.record(z.string(), z.unknown()),
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

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      title: changeRequest.title,
      description: changeRequest.description ?? '',
      change_type: changeRequest.change_type,
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

  useEffect(() => {
    dispatch(fetchDefinitions('change_request'));
  }, [dispatch]);

  // Re-seed form whenever a new CR is passed in (dialog reuse after navigation)
  useEffect(() => {
    if (!open) return;
    reset({
      title: changeRequest.title,
      description: changeRequest.description ?? '',
      change_type: changeRequest.change_type,
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
    >
      <Alert severity="info" sx={{ mb: 1, mt: 1 }}>
        Lifecycle, environment, and subsystem can't be changed after creation. To move a
        change to a different subsystem, cancel this one and raise a new one.
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
