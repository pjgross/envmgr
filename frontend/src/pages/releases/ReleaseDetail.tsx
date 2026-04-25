/**
 * ReleaseDetail — full-page view for an existing release with 5 tabs:
 *   0: Main (lifecycle, fields, transitions)
 *   1: Gates & Test Phases
 *   2: Environments
 *   3: Linked Requests
 *   4: Scope
 *   5: Enterprise (membership)
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Tab,
  Tabs,
  Tooltip,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import HistoryIcon from '@mui/icons-material/History';
import EventNoteIcon from '@mui/icons-material/EventNote';
import { AppDispatch, RootState } from '../../store';
import { fetchRelease, deleteRelease, clearDetail } from '../../store/releaseSlice';
import ReleaseMainTab from '../../components/releases/ReleaseMainTab';
import ReleasePlanTab from '../../components/releases/ReleasePlanTab';
import ReleaseEnvironmentsTab from '../../components/releases/ReleaseEnvironmentsTab';
import ReleaseLinkedRequestsTab from '../../components/releases/ReleaseLinkedRequestsTab';
import ReleaseScopeTab from '../../components/releases/ReleaseScopeTab';
import ReleaseDeploymentsTab from '../../components/releases/ReleaseDeploymentsTab';
import ReleaseStatusHistoryDrawer from '../../components/releases/ReleaseStatusHistoryDrawer';
import ReleaseEventDrawer from '../../components/releases/ReleaseEventDrawer';
import { EnterpriseTabs } from './enterprise/EnterpriseTabs';
import { EnterpriseMembershipTab } from './project/EnterpriseMembershipTab';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  planning: 'info',
  in_progress: 'info',
  submitted: 'warning',
  approved: 'success',
  completed: 'success',
  cancelled: 'error',
};

export default function ReleaseDetail() {
  const { id } = useParams<{ id: string }>();
  const releaseId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const { detail: release, loading, error } = useSelector((s: RootState) => s.release);
  const { confirm, dialog: confirmDialog } = useConfirm();
  const [activeTab, setActiveTab] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [eventLogOpen, setEventLogOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchRelease(releaseId));
    return () => {
      dispatch(clearDetail());
    };
  }, [dispatch, releaseId]);

  const handleDelete = async () => {
    if (!(await confirm({ title: 'Delete release', message: `Delete release "${release?.name}"? This cannot be undone.`, destructive: true }))) return;
    try {
      await dispatch(deleteRelease(releaseId)).unwrap();
      snackbar.success('Release deleted');
      navigate('/releases');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete release');
    }
  };

  if (loading && !release) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error || !release) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography color="error">{error ?? 'Release not found'}</Typography>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/releases')} sx={{ mt: 2 }}>
          Back to Releases
        </Button>
      </Box>
    );
  }

  if (release.release_kind === 'enterprise') {
    return <EnterpriseTabs release={release} />;
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <IconButton onClick={() => navigate('/releases')} size="small">
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          {release.name}
        </Typography>
        <Chip
          label={release.status}
          color={STATUS_COLORS[release.status] ?? 'default'}
          size="small"
        />
        <Chip label={release.release_type} size="small" variant="outlined" />
        <Tooltip title="Status history">
          <IconButton size="small" onClick={() => setHistoryOpen(true)}>
            <HistoryIcon />
          </IconButton>
        </Tooltip>
        <Tooltip title="Event log">
          <IconButton size="small" onClick={() => setEventLogOpen(true)}>
            <EventNoteIcon />
          </IconButton>
        </Tooltip>
        <IconButton color="error" onClick={handleDelete} size="small" title="Delete release">
          <DeleteOutlineIcon />
        </IconButton>
      </Box>

      {/* Tab strip */}
      <Paper sx={{ mb: 2 }}>
        <Tabs
          value={activeTab}
          onChange={(_, v) => setActiveTab(v)}
          sx={{ px: 2 }}
        >
          <Tab label="Main" />
          <Tab label="Gates & Test Phases" />
          <Tab label="Environments" />
          <Tab label="Linked Requests" />
          <Tab label="Scope" />
          <Tab label="Enterprise" />
          <Tab label="Deployments" />
        </Tabs>
      </Paper>

      {/* Tab content */}
      {activeTab === 0 && <ReleaseMainTab releaseId={releaseId} />}
      {activeTab === 1 && <ReleasePlanTab releaseId={releaseId} />}
      {activeTab === 2 && <ReleaseEnvironmentsTab releaseId={releaseId} />}
      {activeTab === 3 && <ReleaseLinkedRequestsTab releaseId={releaseId} />}
      {activeTab === 4 && <ReleaseScopeTab releaseId={releaseId} />}
      {activeTab === 5 && <EnterpriseMembershipTab releaseId={releaseId} />}
      {activeTab === 6 && <ReleaseDeploymentsTab releaseId={releaseId} />}

      {confirmDialog}
      {/* Side drawers */}
      <ReleaseStatusHistoryDrawer
        open={historyOpen}
        releaseId={releaseId}
        onClose={() => setHistoryOpen(false)}
      />
      <ReleaseEventDrawer
        open={eventLogOpen}
        releaseId={releaseId}
        onClose={() => setEventLogOpen(false)}
      />
    </Box>
  );
}
