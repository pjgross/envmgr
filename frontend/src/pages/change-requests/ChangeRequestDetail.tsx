import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditIcon from '@mui/icons-material/Edit';
import { AppDispatch, RootState } from '../../store';
import {
  fetchChangeRequest,
  transitionChangeRequest,
  deleteChangeRequest,
  clearDetail,
} from '../../store/changeRequestSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import TransitionButtons from '../../components/bookings/TransitionButtons';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';
import { useSnackbar } from '../../hooks/useSnackbar';
import { changeRequestService } from '../../services/changeRequestService';
import type { AllowedTransition } from '../../types/bookingLifecycle';
import { CHANGE_TYPE_LABELS } from '../../types/changeRequest';
import ChangeRequestEditDialog from './ChangeRequestEditDialog';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  in_progress: 'info',
  completed: 'info',
};

export default function ChangeRequestDetail() {
  const { id } = useParams<{ id: string }>();
  const crId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const { detail, loading, error } = useSelector((s: RootState) => s.changeRequest);
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['change_request'] ?? []
  );

  const [allowed, setAllowed] = useState<AllowedTransition[]>([]);
  const [editOpen, setEditOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchChangeRequest(crId));
    dispatch(fetchDefinitions('change_request'));
    return () => {
      dispatch(clearDetail());
    };
  }, [dispatch, crId]);

  useEffect(() => {
    if (!detail) return;
    let cancelled = false;
    (async () => {
      try {
        const t = await changeRequestService.getAllowedTransitions(crId);
        if (!cancelled) setAllowed(t);
      } catch {
        if (!cancelled) setAllowed([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [detail, crId]);

  const handleTransition = async (toState: string, label: string) => {
    try {
      const action = await dispatch(
        transitionChangeRequest({ id: crId, data: { to_state: toState } })
      );
      if ('error' in action) {
        throw new Error(action.error.message ?? 'Transition failed');
      }
      snackbar.success(`Transitioned: ${label}`);
      // Refetch for updated history + allowed transitions
      dispatch(fetchChangeRequest(crId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Transition failed');
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this change request?')) return;
    try {
      const action = await dispatch(deleteChangeRequest(crId));
      if ('error' in action) throw new Error(action.error.message ?? 'Delete failed');
      snackbar.success('Change request deleted');
      navigate('/change-requests');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  if (loading && !detail) {
    return (
      <Box sx={{ p: 3 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !detail) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  if (!detail) return null;

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1 }}>
        <IconButton onClick={() => navigate('/change-requests')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          {detail.title}
        </Typography>
        <Chip
          label={detail.status}
          color={STATUS_COLORS[detail.status] ?? 'default'}
        />
        <Button
          size="small"
          startIcon={<EditIcon />}
          onClick={() => setEditOpen(true)}
        >
          Edit
        </Button>
        <Button
          color="error"
          size="small"
          startIcon={<DeleteOutlineIcon />}
          onClick={handleDelete}
        >
          Delete
        </Button>
      </Box>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={4} flexWrap="wrap">
          <Box>
            <Typography variant="caption" color="text.secondary">
              Type
            </Typography>
            <Typography variant="body2">
              {CHANGE_TYPE_LABELS[detail.change_type] ?? detail.change_type}
            </Typography>
          </Box>
          <Box sx={{ minWidth: 200 }}>
            <Typography variant="caption" color="text.secondary">
              Environments
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
              {detail.environments.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  —
                </Typography>
              ) : (
                detail.environments.map((e) => (
                  <Chip
                    key={e.id}
                    size="small"
                    label={e.name}
                    color={
                      detail.derived_environment_ids.includes(e.id) ? 'info' : 'default'
                    }
                    variant="outlined"
                  />
                ))
              )}
              {detail.derived_environments
                .filter((e) => !detail.environments.some((ee) => ee.id === e.id))
                .map((e) => (
                  <Chip
                    key={`derived-${e.id}`}
                    size="small"
                    label={`${e.name} (derived)`}
                    color="info"
                    variant="outlined"
                  />
                ))}
            </Box>
          </Box>
          <Box sx={{ minWidth: 200 }}>
            <Typography variant="caption" color="text.secondary">
              Hosts
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
              {detail.hosts.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  —
                </Typography>
              ) : (
                detail.hosts.map((h) => (
                  <Chip
                    key={h.id}
                    size="small"
                    label={`${h.name}${h.region ? ` · ${h.region}` : ''}`}
                    variant="outlined"
                  />
                ))
              )}
            </Box>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              Subsystem
            </Typography>
            <Typography variant="body2">
              {detail.subsystem_id == null ? '—' : `#${detail.subsystem_id}`}
            </Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">
              Scheduled
            </Typography>
            <Typography variant="body2">
              {new Date(detail.scheduled_start).toLocaleString()} →{' '}
              {new Date(detail.scheduled_end).toLocaleString()}
            </Typography>
          </Box>
          {detail.has_outage && (
            <Box>
              <Typography variant="caption" color="error">
                Outage
              </Typography>
              <Typography variant="body2">
                {detail.outage_start && detail.outage_end
                  ? `${new Date(detail.outage_start).toLocaleString()} → ${new Date(
                      detail.outage_end
                    ).toLocaleString()}`
                  : '—'}
              </Typography>
            </Box>
          )}
        </Stack>
      </Paper>

      {detail.description && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="caption" color="text.secondary">
            Description
          </Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
            {detail.description}
          </Typography>
        </Paper>
      )}

      {customFieldDefs.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Custom Fields
          </Typography>
          <CustomFieldsDisplay
            definitions={customFieldDefs}
            values={(detail.custom_fields ?? {}) as Record<string, unknown>}
          />
        </Paper>
      )}

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Actions
        </Typography>
        {allowed.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No transitions available for your role.
          </Typography>
        ) : (
          <TransitionButtons transitions={allowed} onTransition={handleTransition} />
        )}
      </Paper>

      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          History
        </Typography>
        {detail.history.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No history yet.
          </Typography>
        ) : (
          <Stack spacing={1}>
            {detail.history.map((h) => (
              <Box key={h.id}>
                <Typography variant="body2">
                  {h.field_name
                    ? `Updated ${h.field_name}`
                    : h.to_state
                      ? h.from_state
                        ? `State: ${h.from_state} → ${h.to_state}`
                        : `Initial state: ${h.to_state}`
                      : 'Updated'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {new Date(h.changed_at).toLocaleString()} · user #{h.changed_by}
                  {h.notes ? ` · ${h.notes}` : ''}
                </Typography>
                <Divider sx={{ mt: 1 }} />
              </Box>
            ))}
          </Stack>
        )}
      </Paper>

      <ChangeRequestEditDialog
        open={editOpen}
        onClose={() => setEditOpen(false)}
        changeRequest={detail}
      />
    </Box>
  );
}
