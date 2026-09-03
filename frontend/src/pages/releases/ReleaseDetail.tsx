/**
 * ReleaseDetail — full-page view for an existing release. The active tab is
 * held in `?tab=` (see `useUrlTab`), keyed as:
 *   main: Main (lifecycle, fields, transitions)
 *   gates: Gates & Test Phases
 *   systems: Systems
 *   environments: Environments
 *   requests: Linked Requests
 *   scope: Scope
 *   raid: RAID
 *   enterprise: Enterprise (membership)
 *   deployments: Deployments
 *   pir: PIR (Post-Implementation Review)
 *   rollback: Rollback
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import { useUrlTab } from '../../hooks/useUrlTab';
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
import RaidTab from '../../components/releases/raid/RaidTab';
import ReleaseDeploymentsTab from '../../components/releases/ReleaseDeploymentsTab';
import ReleasePirTab from '../../components/releases/pir/ReleasePirTab';
import ReleaseSystemsTab from '../../components/releases/ReleaseSystemsTab';
import ReleaseStatusHistoryDrawer from '../../components/releases/ReleaseStatusHistoryDrawer';
import ReleaseEventDrawer from '../../components/releases/ReleaseEventDrawer';
import ReadinessBanner from '../../components/releases/ReadinessBanner';
import RollbackPanel from '../../components/releases/RollbackPanel';
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

const RELEASE_TABS = [
  { key: 'main', label: 'Main' },
  { key: 'gates', label: 'Gates & Test Phases' },
  { key: 'systems', label: 'Systems' },
  { key: 'environments', label: 'Environments' },
  { key: 'requests', label: 'Linked Requests' },
  { key: 'scope', label: 'Scope' },
  { key: 'raid', label: 'RAID' },
  { key: 'enterprise', label: 'Enterprise' },
  { key: 'deployments', label: 'Deployments' },
  { key: 'pir', label: 'PIR' },
  { key: 'rollback', label: 'Rollback' },
] as const;

export default function ReleaseDetail() {
  const { id } = useParams<{ id: string }>();
  const releaseId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const { detail: release, loading, error } = useSelector((s: RootState) => s.release);
  const { confirm, dialog: confirmDialog } = useConfirm();
  const [activeTab, setActiveTab] = useUrlTab(
    RELEASE_TABS.map((t) => t.key),
    'main',
  );
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

      <ReadinessBanner releaseId={releaseId} />

      {/* Tab strip */}
      <Paper sx={{ mb: 2 }}>
        <Tabs
          value={activeTab}
          onChange={(_, v: string) => setActiveTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          sx={{ px: 2 }}
        >
          {RELEASE_TABS.map((t) => (
            <Tab key={t.key} value={t.key} label={t.label} />
          ))}
        </Tabs>
      </Paper>

      {/* Tab content */}
      {activeTab === 'main' && <ReleaseMainTab releaseId={releaseId} />}
      {activeTab === 'gates' && <ReleasePlanTab releaseId={releaseId} />}
      {activeTab === 'systems' && <ReleaseSystemsTab releaseId={releaseId} />}
      {activeTab === 'environments' && <ReleaseEnvironmentsTab releaseId={releaseId} />}
      {activeTab === 'requests' && <ReleaseLinkedRequestsTab releaseId={releaseId} />}
      {activeTab === 'scope' && <ReleaseScopeTab releaseId={releaseId} />}
      {activeTab === 'raid' && <RaidTab releaseId={releaseId} />}
      {activeTab === 'enterprise' && <EnterpriseMembershipTab releaseId={releaseId} />}
      {activeTab === 'deployments' && <ReleaseDeploymentsTab releaseId={releaseId} />}
      {activeTab === 'pir' && <ReleasePirTab releaseId={releaseId} />}
      {activeTab === 'rollback' && <RollbackPanel releaseId={releaseId} />}

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
