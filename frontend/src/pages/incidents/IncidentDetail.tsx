/**
 * IncidentDetail — full detail view for a single incident.
 *
 * Route: /incidents/:id
 *
 * Sections:
 *   - Header: title, severity chip, status chip, transition buttons
 *   - Details: description, detected/resolved timestamps, source/ext-ref, env, causal release, system/subsystem
 *   - Fix Release panel: fix release summary + changes grouped by epic
 *   - PIR panel: post-implementation review (status, root cause, action plan, summary, release link)
 *   - Custom Fields panel: read-only key/value display
 *   - Status History timeline
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams, Link as RouterLink } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemText,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import { AppDispatch, RootState } from '../../store';
import { fetchIncident, transitionIncident, deleteIncident, clearDetail } from '../../store/incidentSlice';
import { SEVERITY_COLOR } from '../../utils/incidentSeverity';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import { pirService } from '../../services/pirService';

export default function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const incidentId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const [pirCreating, setPirCreating] = useState(false);

  const detail = useSelector((s: RootState) => s.incident.detail);
  const loading = useSelector((s: RootState) => s.incident.loading);
  const error = useSelector((s: RootState) => s.incident.error);

  useEffect(() => {
    dispatch(fetchIncident(incidentId));
    return () => {
      dispatch(clearDetail());
    };
  }, [dispatch, incidentId]);

  const handleTransition = async (toState: string) => {
    try {
      await dispatch(transitionIncident({ id: incidentId, to_state: toState })).unwrap();
      snackbar.success(`Transitioned to ${toState}`);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Transition failed');
    }
  };

  const handleDelete = async () => {
    if (
      !(await confirm({
        title: 'Delete incident',
        message: `Delete incident "${detail?.title}"? This cannot be undone.`,
        destructive: true,
      }))
    )
      return;
    try {
      await dispatch(deleteIncident(incidentId)).unwrap();
      snackbar.success('Incident deleted');
      navigate('/incidents');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete incident');
    }
  };

  const handleCreatePir = async () => {
    if (!detail?.fix_release_id) return;
    setPirCreating(true);
    try {
      await pirService.create(detail.fix_release_id, { incident_id: detail.id });
      dispatch(fetchIncident(incidentId));
      snackbar.success('PIR created');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create PIR');
    } finally {
      setPirCreating(false);
    }
  };

  if (loading && !detail) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !detail || detail.id !== incidentId) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography color="error">{error ?? 'Incident not found'}</Typography>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/incidents')} sx={{ mt: 2 }}>
          Back to Incidents
        </Button>
      </Box>
    );
  }

  const customFieldEntries = detail.custom_fields
    ? Object.entries(detail.custom_fields)
    : [];

  return (
    <Box sx={{ p: 3 }}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        <IconButton onClick={() => navigate('/incidents')} size="small">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          {detail.title}
        </Typography>
        <Chip
          label={detail.severity}
          color={SEVERITY_COLOR[detail.severity] ?? 'default'}
          size="small"
        />
        <Chip label={detail.status} size="small" variant="outlined" />

        {/* Lifecycle transition buttons */}
        {detail.allowed_transitions.map((t) => (
          <Button
            key={t.to_state}
            size="small"
            variant="outlined"
            onClick={() => handleTransition(t.to_state)}
          >
            {t.label}
          </Button>
        ))}

        <IconButton
          size="small"
          onClick={() => navigate(`/incidents/${incidentId}/edit`)}
          title="Edit incident"
        >
          <EditIcon />
        </IconButton>
        <IconButton
          size="small"
          color="error"
          onClick={handleDelete}
          title="Delete incident"
        >
          <DeleteOutlineIcon />
        </IconButton>
      </Box>

      {/* ── Details block ──────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Details
        </Typography>
        <Divider sx={{ mb: 1.5 }} />

        {detail.description && (
          <Typography variant="body2" sx={{ mb: 1.5, whiteSpace: 'pre-wrap' }}>
            {detail.description}
          </Typography>
        )}

        <Stack spacing={0.75}>
          <Stack direction="row" spacing={2}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
              Detected at
            </Typography>
            <Typography variant="body2">
              {new Date(detail.detected_at).toLocaleString()}
            </Typography>
          </Stack>

          {detail.resolved_at && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Resolved at
              </Typography>
              <Typography variant="body2">
                {new Date(detail.resolved_at).toLocaleString()}
              </Typography>
            </Stack>
          )}

          <Stack direction="row" spacing={2}>
            <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
              Source
            </Typography>
            <Typography variant="body2">{detail.source}</Typography>
          </Stack>

          {detail.external_ref && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                External Ref
              </Typography>
              <Typography variant="body2">{detail.external_ref}</Typography>
            </Stack>
          )}

          {detail.environment_name && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Environment
              </Typography>
              <Typography variant="body2">{detail.environment_name}</Typography>
            </Stack>
          )}

          {detail.release && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Causal Release
              </Typography>
              <Typography
                variant="body2"
                component={RouterLink}
                to={`/releases/${detail.release.id}`}
                sx={{ color: 'primary.main', textDecoration: 'none' }}
              >
                {detail.release.name}
              </Typography>
            </Stack>
          )}

          {detail.system_name && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                System
              </Typography>
              <Typography variant="body2">{detail.system_name}</Typography>
            </Stack>
          )}

          {detail.subsystem_name && (
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Subsystem
              </Typography>
              <Typography variant="body2">{detail.subsystem_name}</Typography>
            </Stack>
          )}
        </Stack>
      </Paper>

      {/* ── Fix Release panel ──────────────────────────────────────────── */}
      {detail.fix_release && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Fix Release
          </Typography>
          <Divider sx={{ mb: 1.5 }} />

          <Stack spacing={0.75} sx={{ mb: 2 }}>
            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Release
              </Typography>
              <Typography
                variant="body2"
                component={RouterLink}
                to={`/releases/${detail.fix_release.id}`}
                sx={{ color: 'primary.main', textDecoration: 'none' }}
              >
                {detail.fix_release.name}
              </Typography>
            </Stack>

            {detail.fix_release.target_date && (
              <Stack direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                  Fix ETA
                </Typography>
                <Typography variant="body2">
                  {new Date(detail.fix_release.target_date).toLocaleDateString()}
                </Typography>
              </Stack>
            )}

            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Status
              </Typography>
              <Chip label={detail.fix_release.status} size="small" variant="outlined" />
            </Stack>
          </Stack>

          {/* Changes grouped by epic */}
          {Object.keys(detail.fix_release_changes_by_epic).length > 0 && (
            <>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Scope Changes
              </Typography>
              {Object.entries(detail.fix_release_changes_by_epic).map(([epicKey, changes]) => (
                <Box key={epicKey} sx={{ mb: 2 }}>
                  <Typography
                    variant="overline"
                    color="text.secondary"
                    sx={{ display: 'block', mb: 0.5 }}
                  >
                    {epicKey === 'ungrouped' ? 'No Epic' : `Epic ${epicKey}`}
                  </Typography>
                  <List dense disablePadding>
                    {changes.map((c) => (
                      <ListItem key={c.id} disablePadding sx={{ pl: 1 }}>
                        <ListItemText
                          primary={
                            <Typography variant="body2">{c.title}</Typography>
                          }
                        />
                      </ListItem>
                    ))}
                  </List>
                </Box>
              ))}
            </>
          )}
        </Paper>
      )}

      {/* ── PIR panel ──────────────────────────────────────────────────── */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Post-Implementation Review
        </Typography>
        <Divider sx={{ mb: 1.5 }} />

        {detail.pir ? (
          <Stack spacing={0.75}>
            <Stack direction="row" spacing={2} alignItems="center">
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Status
              </Typography>
              <Chip
                label={detail.pir.status === 'complete' ? 'Complete' : 'Draft'}
                color={detail.pir.status === 'complete' ? 'success' : 'warning'}
                size="small"
              />
            </Stack>

            {detail.pir.summary && (
              <Stack direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                  Summary
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                  {detail.pir.summary}
                </Typography>
              </Stack>
            )}

            {detail.pir.root_cause && (
              <Stack direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                  Root Cause
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                  {detail.pir.root_cause}
                </Typography>
              </Stack>
            )}

            {detail.pir.action_plan && (
              <Stack direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                  Action Plan
                </Typography>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                  {detail.pir.action_plan}
                </Typography>
              </Stack>
            )}

            <Stack direction="row" spacing={2}>
              <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                Release
              </Typography>
              <Typography
                variant="body2"
                component={RouterLink}
                to={`/releases/${detail.pir.release_id}`}
                sx={{ color: 'primary.main', textDecoration: 'none' }}
              >
                {detail.fix_release_id === detail.pir.release_id && detail.fix_release
                  ? detail.fix_release.name
                  : 'View release'}
              </Typography>
            </Stack>
          </Stack>
        ) : (
          <Stack spacing={1}>
            <Box>
              <Button
                variant="outlined"
                size="small"
                disabled={!detail.fix_release_id || pirCreating}
                onClick={handleCreatePir}
              >
                {pirCreating ? 'Creating…' : 'Create PIR'}
              </Button>
            </Box>
            {!detail.fix_release_id && (
              <Typography variant="caption" color="text.secondary">
                Link a fix release to create a PIR.
              </Typography>
            )}
          </Stack>
        )}
      </Paper>

      {/* ── Custom Fields panel ────────────────────────────────────────── */}
      {customFieldEntries.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Custom Fields
          </Typography>
          <Divider sx={{ mb: 1.5 }} />
          <Stack spacing={0.75}>
            {customFieldEntries.map(([key, value]) => (
              <Stack key={key} direction="row" spacing={2}>
                <Typography variant="body2" color="text.secondary" sx={{ minWidth: 160 }}>
                  {key}
                </Typography>
                <Typography variant="body2">{String(value ?? '—')}</Typography>
              </Stack>
            ))}
          </Stack>
        </Paper>
      )}

      {/* ── Status History ─────────────────────────────────────────────── */}
      {detail.status_history.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Status History
          </Typography>
          <Divider sx={{ mb: 1.5 }} />
          <List dense disablePadding>
            {detail.status_history.map((h, idx) => (
              <ListItem key={idx} disablePadding sx={{ py: 0.25 }}>
                <ListItemText
                  primary={
                    <Typography variant="body2">
                      {h.from_state ? (
                        <>
                          <strong>{h.from_state}</strong>
                          {' → '}
                          <strong>{h.to_state}</strong>
                        </>
                      ) : (
                        <>
                          Created as <strong>{h.to_state}</strong>
                        </>
                      )}
                    </Typography>
                  }
                  secondary={
                    <Typography variant="caption" color="text.secondary">
                      {new Date(h.changed_at).toLocaleString()}
                    </Typography>
                  }
                />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}

      {confirmDialog}
    </Box>
  );
}
