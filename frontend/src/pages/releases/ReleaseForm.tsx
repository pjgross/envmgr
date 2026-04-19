/**
 * ReleaseForm — create / edit a release.
 *
 * For new releases this renders just the "Main" fields in a dialog.
 * After the first save the user is redirected to /releases/:id where the full
 * tab shell (T30–T34) is available.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AppDispatch } from '../../store';
import {
  fetchLifecycleTemplates,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { createRelease, updateRelease, fetchRelease } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ReleaseResponse, ReleaseCreatePayload, ReleaseUpdatePayload } from '../../types/release';

// ---- Tabs ----
interface TabPanelProps {
  children?: React.ReactNode;
  value: number;
  index: number;
}
function TabPanel({ children, value, index }: TabPanelProps) {
  if (value !== index) return null;
  return <Box sx={{ pt: 2 }}>{children}</Box>;
}

// ---- Schema ----
const schema = z.object({
  name: z.string().trim().min(1, 'Name is required'),
  description: z.string().optional(),
  release_type: z.string().min(1, 'Type is required'),
  release_kind: z.enum(['project', 'enterprise']),
  lifecycle_template_id: z.number().nullable(),
  target_date: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

const RELEASE_TYPES = ['project', 'hotfix', 'patch', 'major', 'minor'];

// ---- Props ----
interface ReleaseFormProps {
  open: boolean;
  onClose: () => void;
  /** When provided, the form acts as an edit dialog rather than create. */
  release?: ReleaseResponse | null;
}

function buildDefaults(release?: ReleaseResponse | null): FormValues {
  return {
    name: release?.name ?? '',
    description: release?.description ?? '',
    release_type: release?.release_type ?? 'project',
    release_kind: (release?.release_kind as 'project' | 'enterprise') ?? 'project',
    lifecycle_template_id: release?.lifecycle_template_id ?? null,
    target_date: release?.target_date
      ? new Date(release.target_date).toISOString().slice(0, 10)
      : '',
  };
}

export default function ReleaseForm({ open, onClose, release }: ReleaseFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const isEdit = !!release;

  const lifecycles = useSelector(selectTemplatesForEntity('release'));

  const [activeTab, setActiveTab] = useState(0);

  const { control, handleSubmit, reset, setValue } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: buildDefaults(release),
  });

  useEffect(() => {
    dispatch(fetchLifecycleTemplates('release'));
  }, [dispatch]);

  useEffect(() => {
    if (open) {
      reset(buildDefaults(release));
      setActiveTab(0);
    }
  }, [open, release, reset]);

  // Auto-select default lifecycle template
  useEffect(() => {
    if (!isEdit && lifecycles.length > 0) {
      const defaultTpl = lifecycles.find((t) => t.is_default) ?? lifecycles[0];
      setValue('lifecycle_template_id', defaultTpl.id);
    }
  }, [lifecycles, isEdit, setValue]);

  const handleClose = () => {
    reset(buildDefaults());
    onClose();
  };

  // HTML <input type="date"> yields "YYYY-MM-DD". Backend expects ISO datetime.
  const toIsoDatetime = (d: string | undefined | null): string | null =>
    d ? `${d}T00:00:00Z` : null;

  const onSubmit = async (values: FormValues) => {
    try {
      if (isEdit && release) {
        const payload: ReleaseUpdatePayload = {
          name: values.name,
          description: values.description || null,
          release_type: values.release_type,
          target_date: toIsoDatetime(values.target_date),
        };
        await dispatch(updateRelease({ id: release.id, data: payload })).unwrap();
        dispatch(fetchRelease(release.id));
        snackbar.success('Release updated');
        handleClose();
      } else {
        const payload: ReleaseCreatePayload = {
          name: values.name,
          description: values.description || null,
          release_type: values.release_type,
          release_kind: values.release_kind,
          lifecycle_template_id: values.lifecycle_template_id ?? undefined,
          target_date: toIsoDatetime(values.target_date),
        };
        const result = await dispatch(createRelease(payload)).unwrap();
        snackbar.success('Release created');
        handleClose();
        navigate(`/releases/${result.id}`);
      }
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? `${detail[0].loc?.join?.('.') ?? 'field'}: ${detail[0].msg}`
          : err instanceof Error ? err.message : 'Failed to save release';
      snackbar.error(message);
    }
  };

  const savedId = release?.id;
  const tabsDisabled = !savedId;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Release' : 'New Release'}</DialogTitle>
      <DialogContent>
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          sx={{ borderBottom: 1, borderColor: 'divider', mb: 1 }}
        >
          <Tab label="Main" />
          <Tab label="Gates & Test Phases" disabled={tabsDisabled} />
          <Tab label="Environments" disabled={tabsDisabled} />
          <Tab label="Linked Requests" disabled={tabsDisabled} />
          <Tab label="Scope" disabled={tabsDisabled} />
        </Tabs>

        {tabsDisabled && activeTab === 0 && (
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            Save this release to unlock the remaining tabs.
          </Typography>
        )}

        <Box component="form" id="release-form" onSubmit={handleSubmit(onSubmit)}>
          <TabPanel value={activeTab} index={0}>
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <Controller
                control={control}
                name="name"
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    label="Name"
                    required
                    fullWidth
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                  />
                )}
              />

              <Controller
                control={control}
                name="release_type"
                render={({ field, fieldState }) => (
                  <TextField
                    {...field}
                    select
                    label="Release Type"
                    required
                    fullWidth
                    error={!!fieldState.error}
                    helperText={fieldState.error?.message}
                  >
                    {RELEASE_TYPES.map((t) => (
                      <MenuItem key={t} value={t}>
                        {t}
                      </MenuItem>
                    ))}
                  </TextField>
                )}
              />

              {!isEdit && (
                <Controller
                  control={control}
                  name="release_kind"
                  render={({ field }) => (
                    <TextField {...field} select label="Kind" fullWidth>
                      <MenuItem value="project">Project</MenuItem>
                      <MenuItem value="enterprise">Enterprise</MenuItem>
                    </TextField>
                  )}
                />
              )}

              {!isEdit && (
                <Controller
                  control={control}
                  name="lifecycle_template_id"
                  render={({ field, fieldState }) => (
                    <TextField
                      select
                      label="Lifecycle"
                      fullWidth
                      value={field.value ?? ''}
                      onChange={(e) =>
                        field.onChange(e.target.value === '' ? null : Number(e.target.value))
                      }
                      error={!!fieldState.error}
                      helperText={fieldState.error?.message}
                    >
                      {lifecycles.map((t) => (
                        <MenuItem key={t.id} value={t.id}>
                          {t.name}
                          {t.is_default ? ' (default)' : ''}
                        </MenuItem>
                      ))}
                    </TextField>
                  )}
                />
              )}

              <Controller
                control={control}
                name="target_date"
                render={({ field }) => (
                  <TextField
                    {...field}
                    label="Target Date"
                    type="date"
                    fullWidth
                    InputLabelProps={{ shrink: true }}
                  />
                )}
              />

              <Controller
                control={control}
                name="description"
                render={({ field }) => (
                  <TextField
                    {...field}
                    label="Description"
                    multiline
                    rows={3}
                    fullWidth
                  />
                )}
              />
            </Box>
          </TabPanel>
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button type="submit" form="release-form" variant="contained">
          {isEdit ? 'Save' : 'Create Release'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
