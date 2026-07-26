/**
 * ReleaseMainTab — primary fields + lifecycle transition controls.
 *
 * - Renders LifecycleAwareFieldsPanel for standard + custom fields
 * - Renders TransitionControls for allowed state transitions
 * - Shows DependencyAlertBanner when there are outstanding alerts
 * - Saves field edits inline via PATCH /releases/:id
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import EditIcon from '@mui/icons-material/Edit';
import { AppDispatch, RootState } from '../../store';
import {
  fetchRelease,
  updateRelease,
  transitionRelease,
  fetchDependencyAlerts,
} from '../../store/releaseSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { releaseService } from '../../services/releaseService';
import LifecycleAwareFieldsPanel from '../lifecycle/LifecycleAwareFieldsPanel';
import TransitionControls from '../lifecycle/TransitionControls';
import DependencyAlertBanner from './DependencyAlertBanner';
import { useSnackbar } from '../../hooks/useSnackbar';
import ReleaseForm from '../../pages/releases/ReleaseForm';
import type { BookingLifecycleTemplate } from '../../types/bookingLifecycle';

interface Props {
  releaseId: number;
}

export default function ReleaseMainTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();

  const release = useSelector((s: RootState) => s.release.detail);
  const user = useSelector((s: RootState) => s.auth.user);
  const dependencyAlerts = useSelector((s: RootState) => s.release.dependencyAlerts);
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['release'] ?? []
  );

  const [lifecycleTpl, setLifecycleTpl] = useState<BookingLifecycleTemplate | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    if (!releaseId) return;
    dispatch(fetchDefinitions('release'));
    dispatch(fetchDependencyAlerts(releaseId));
    releaseService
      .getLifecycle(releaseId)
      .then(setLifecycleTpl)
      .catch(() => setLifecycleTpl(null));
  }, [dispatch, releaseId]);

  const userRole = user?.role ?? 'Viewer';

  const handleTransition = async (toState: string, notes?: string) => {
    try {
      await dispatch(
        transitionRelease({ id: releaseId, data: { to_state: toState, notes } })
      ).unwrap();
      // Reload lifecycle definition in case state changes field permissions
      const tpl = await releaseService.getLifecycle(releaseId);
      setLifecycleTpl(tpl);
      snackbar.success(`Transitioned to ${toState}`);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Transition failed');
    }
  };

  const handleStandardChange = async (key: string, value: unknown) => {
    try {
      await dispatch(
        updateRelease({ id: releaseId, data: { [key]: value } })
      ).unwrap();
      dispatch(fetchRelease(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to update field');
    }
  };

  const handleCustomChange = async (key: string, value: unknown) => {
    if (!release) return;
    const updated = { ...(release.custom_fields ?? {}), [key]: value };
    try {
      await dispatch(
        updateRelease({ id: releaseId, data: { custom_fields: updated } })
      ).unwrap();
      dispatch(fetchRelease(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to update custom field');
    }
  };

  if (!release) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  const standardValues: Record<string, unknown> = {
    name: release.name,
    description: release.description,
    release_type: release.release_type,
    target_date: release.target_date,
    actual_date: release.actual_date,
  };

  const fieldPermissions = lifecycleTpl?.definition?.field_permissions ?? {};

  return (
    <Box>
      <DependencyAlertBanner releaseId={releaseId} alerts={dependencyAlerts} />

      {/* Lifecycle transition controls */}
      {lifecycleTpl && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Stack spacing={1}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <Typography variant="body2" color="text.secondary">
                Status:
              </Typography>
              <Typography variant="body2" fontWeight="medium">
                {release.status}
              </Typography>
            </Box>
            <TransitionControls
              currentState={release.status}
              userRole={userRole}
              lifecycleDefinition={lifecycleTpl.definition}
              recordValues={{
                ...standardValues,
                custom_fields: (release.custom_fields ?? {}) as Record<string, unknown>,
              }}
              onTransition={handleTransition}
            />
          </Stack>
        </Paper>
      )}

      {/* Field permissions panel */}
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="subtitle1" fontWeight="medium">
            Details
          </Typography>
          <Button
            size="small"
            startIcon={<EditIcon />}
            onClick={() => setEditOpen(true)}
          >
            Edit
          </Button>
        </Box>
        <Divider sx={{ mb: 2 }} />

        {Object.keys(fieldPermissions).length > 0 ? (
          <LifecycleAwareFieldsPanel
            entityType="release"
            entitySubtype={release.release_type}
            currentState={release.status}
            userRole={userRole}
            fieldPermissions={fieldPermissions}
            standardValues={standardValues}
            customFieldDefinitions={customFieldDefs}
            customFieldValues={(release.custom_fields ?? {}) as Record<string, unknown>}
            onStandardChange={handleStandardChange}
            onCustomChange={handleCustomChange}
            readOnly
          />
        ) : (
          <Stack spacing={1}>
            <Typography variant="body2">
              <strong>Name:</strong> {release.name}
            </Typography>
            <Typography variant="body2">
              <strong>Type:</strong> {release.release_type}
            </Typography>
            <Typography variant="body2">
              <strong>Kind:</strong> {release.release_kind}
            </Typography>
            {release.target_date && (
              <Typography variant="body2">
                <strong>Target Date:</strong>{' '}
                {new Date(release.target_date).toLocaleDateString()}
              </Typography>
            )}
            {release.actual_date && (
              <Typography variant="body2">
                <strong>Actual Date:</strong>{' '}
                {new Date(release.actual_date).toLocaleDateString()}
              </Typography>
            )}
            {release.description && (
              <Typography variant="body2">
                <strong>Description:</strong> {release.description}
              </Typography>
            )}
          </Stack>
        )}

        {/* Scope deadline — project releases only; shown regardless of the
            lifecycle field-permissions config since it isn't a standard field. */}
        {release.release_kind === 'project' && (
          <Typography variant="body2" sx={{ mt: 1 }}>
            <strong>Scope Deadline:</strong>{' '}
            {release.scope_deadline
              ? new Date(release.scope_deadline).toLocaleDateString()
              : 'Not set'}
          </Typography>
        )}
      </Paper>

      <ReleaseForm open={editOpen} onClose={() => setEditOpen(false)} release={release} />
    </Box>
  );
}
