import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchEnvironment,
  updateEnvironment,
  fetchEnvironmentSystems,
  addSystemToEnvironment,
  updateSystemInEnvironment,
  removeSystemFromEnvironment,
} from '../../store/environmentSlice';
import { fetchSystems } from '../../store/systemSlice';
import type {
  EnvironmentUpdate,
  EnvironmentStatus,
  EnvironmentSystemResponse,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
  EnvironmentSystemStatus,
} from '../../types/environment';

const STATUS_COLORS: Record<EnvironmentStatus, 'success' | 'warning' | 'default' | 'error'> = {
  active: 'success',
  maintenance: 'warning',
  inactive: 'default',
  decommissioned: 'error',
};

const ENV_SYS_STATUS_COLORS: Record<EnvironmentSystemStatus, 'success' | 'warning' | 'default'> = {
  active: 'success',
  mock: 'warning',
  inactive: 'default',
};

interface EnvFormValues {
  name: string;
  description: string;
  environment_type: string;
  status: EnvironmentStatus;
}

interface SysFormValues {
  system_id: number | '';
  status: EnvironmentSystemStatus;
  mock_notes: string;
}

const emptySysForm: SysFormValues = { system_id: '', status: 'active', mock_notes: '' };

export default function EnvironmentDetail() {
  const { id } = useParams<{ id: string }>();
  const envId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const { currentEnvironment, environmentSystems, loading, error } = useSelector(
    (state: RootState) => state.environment
  );
  const { systems } = useSelector((state: RootState) => state.system);

  const [tab, setTab] = useState(0);

  // Overview edit state
  const [editMode, setEditMode] = useState(false);
  const [envForm, setEnvForm] = useState<EnvFormValues>({
    name: '',
    description: '',
    environment_type: '',
    status: 'active',
  });
  const [envFormError, setEnvFormError] = useState('');

  // System dialog state
  const [sysDialogOpen, setSysDialogOpen] = useState(false);
  const [sysEditTarget, setSysEditTarget] = useState<EnvironmentSystemResponse | null>(null);
  const [sysForm, setSysForm] = useState<SysFormValues>(emptySysForm);
  const [sysFormError, setSysFormError] = useState('');
  const [sysDeleteTarget, setSysDeleteTarget] = useState<EnvironmentSystemResponse | null>(null);

  useEffect(() => {
    dispatch(fetchEnvironment(envId));
    dispatch(fetchEnvironmentSystems(envId));
    dispatch(fetchSystems());
  }, [dispatch, envId]);

  useEffect(() => {
    if (currentEnvironment) {
      setEnvForm({
        name: currentEnvironment.name,
        description: currentEnvironment.description ?? '',
        environment_type: currentEnvironment.environment_type,
        status: currentEnvironment.status,
      });
    }
  }, [currentEnvironment]);

  const handleEnvUpdate = async () => {
    if (!envForm.name.trim()) {
      setEnvFormError('Name is required');
      return;
    }
    try {
      const data: EnvironmentUpdate = {
        name: envForm.name,
        description: envForm.description || undefined,
        environment_type: envForm.environment_type,
        status: envForm.status,
      };
      await dispatch(updateEnvironment({ id: envId, data })).unwrap();
      setEditMode(false);
      setEnvFormError('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setEnvFormError(message || 'Failed to update environment');
    }
  };

  const openSysCreate = () => {
    setSysEditTarget(null);
    setSysForm(emptySysForm);
    setSysFormError('');
    setSysDialogOpen(true);
  };

  const openSysEdit = (envSys: EnvironmentSystemResponse) => {
    setSysEditTarget(envSys);
    setSysForm({
      system_id: envSys.system_id,
      status: envSys.status,
      mock_notes: envSys.mock_notes ?? '',
    });
    setSysFormError('');
    setSysDialogOpen(true);
  };

  const handleSysSave = async () => {
    try {
      if (sysEditTarget) {
        const data: EnvironmentSystemUpdate = {
          status: sysForm.status,
          mock_notes: sysForm.mock_notes || undefined,
        };
        await dispatch(
          updateSystemInEnvironment({ envId, systemId: sysEditTarget.system_id, data })
        ).unwrap();
      } else {
        if (!sysForm.system_id) {
          setSysFormError('Please select a system');
          return;
        }
        const data: EnvironmentSystemCreate = {
          system_id: sysForm.system_id as number,
          status: sysForm.status,
          mock_notes: sysForm.mock_notes || undefined,
        };
        await dispatch(addSystemToEnvironment({ envId, data })).unwrap();
      }
      setSysDialogOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSysFormError(message || 'Failed to save');
    }
  };

  const handleSysDelete = async () => {
    if (!sysDeleteTarget) return;
    try {
      await dispatch(
        removeSystemFromEnvironment({ envId, systemId: sysDeleteTarget.system_id })
      ).unwrap();
    } finally {
      setSysDeleteTarget(null);
    }
  };

  // Systems already assigned (to exclude from add dropdown)
  const assignedSystemIds = new Set(environmentSystems.map((s) => s.system_id));
  const availableSystems = systems.filter((s) => !assignedSystemIds.has(s.id));

  if (loading && !currentEnvironment) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (error && !currentEnvironment) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1 }}>
        <IconButton onClick={() => navigate('/environments')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          {currentEnvironment?.name ?? '…'}
        </Typography>
        {currentEnvironment && (
          <Chip
            label={currentEnvironment.status}
            size="small"
            color={STATUS_COLORS[currentEnvironment.status]}
          />
        )}
        {!editMode && tab === 0 && (
          <Button startIcon={<EditIcon />} onClick={() => setEditMode(true)}>
            Edit
          </Button>
        )}
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Overview" />
        <Tab label="Systems" />
        <Tab label="Versions" />
      </Tabs>

      {/* Overview Tab */}
      {tab === 0 && (
        <Paper sx={{ p: 3 }}>
          {editMode ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {envFormError && <Alert severity="error">{envFormError}</Alert>}
              <TextField
                label="Name"
                required
                value={envForm.name}
                onChange={(e) => setEnvForm({ ...envForm, name: e.target.value })}
              />
              <TextField
                label="Description"
                value={envForm.description}
                onChange={(e) => setEnvForm({ ...envForm, description: e.target.value })}
                multiline
                rows={3}
              />
              <TextField
                label="Environment Type"
                value={envForm.environment_type}
                onChange={(e) => setEnvForm({ ...envForm, environment_type: e.target.value })}
                placeholder="e.g. staging, uat, dev"
              />
              <FormControl>
                <InputLabel>Status</InputLabel>
                <Select
                  label="Status"
                  value={envForm.status}
                  onChange={(e) =>
                    setEnvForm({ ...envForm, status: e.target.value as EnvironmentStatus })
                  }
                >
                  <MenuItem value="active">Active</MenuItem>
                  <MenuItem value="inactive">Inactive</MenuItem>
                  <MenuItem value="maintenance">Maintenance</MenuItem>
                  <MenuItem value="decommissioned">Decommissioned</MenuItem>
                </Select>
              </FormControl>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button variant="contained" onClick={handleEnvUpdate} disabled={loading}>
                  Save
                </Button>
                <Button onClick={() => setEditMode(false)}>Cancel</Button>
              </Box>
            </Box>
          ) : (
            <Box>
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">Name</Typography>
                <Typography>{currentEnvironment?.name}</Typography>
              </Box>
              <Divider sx={{ my: 1 }} />
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">Description</Typography>
                <Typography>{currentEnvironment?.description ?? '—'}</Typography>
              </Box>
              <Divider sx={{ my: 1 }} />
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">Environment Type</Typography>
                <Typography>{currentEnvironment?.environment_type}</Typography>
              </Box>
              <Divider sx={{ my: 1 }} />
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">Status</Typography>
                <Box>
                  {currentEnvironment && (
                    <Chip
                      label={currentEnvironment.status}
                      size="small"
                      color={STATUS_COLORS[currentEnvironment.status]}
                    />
                  )}
                </Box>
              </Box>
              {currentEnvironment?.custom_fields && (
                <>
                  <Divider sx={{ my: 1 }} />
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="overline" color="text.secondary">Custom Fields</Typography>
                    <Box
                      component="pre"
                      sx={{
                        mt: 0.5,
                        p: 1,
                        bgcolor: 'grey.100',
                        borderRadius: 1,
                        fontSize: 12,
                        overflowX: 'auto',
                      }}
                    >
                      {JSON.stringify(currentEnvironment.custom_fields, null, 2)}
                    </Box>
                  </Box>
                </>
              )}
              <Divider sx={{ my: 1 }} />
              <Box sx={{ display: 'flex', gap: 4 }}>
                <Box>
                  <Typography variant="overline" color="text.secondary">Created</Typography>
                  <Typography variant="body2">
                    {currentEnvironment
                      ? new Date(currentEnvironment.created_at).toLocaleString()
                      : '—'}
                  </Typography>
                </Box>
                <Box>
                  <Typography variant="overline" color="text.secondary">Updated</Typography>
                  <Typography variant="body2">
                    {currentEnvironment
                      ? new Date(currentEnvironment.updated_at).toLocaleString()
                      : '—'}
                  </Typography>
                </Box>
              </Box>
            </Box>
          )}
        </Paper>
      )}

      {/* Systems Tab */}
      {tab === 1 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openSysCreate}>
              Add System
            </Button>
          </Box>

          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>System</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Mock Notes</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {environmentSystems.map((envSys) => (
                  <TableRow key={envSys.id} hover>
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {envSys.system.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={envSys.status}
                        size="small"
                        color={ENV_SYS_STATUS_COLORS[envSys.status]}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {envSys.mock_notes ?? '—'}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openSysEdit(envSys)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Remove">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setSysDeleteTarget(envSys)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
                {environmentSystems.length === 0 && !loading && (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      <Typography color="text.secondary" py={3}>
                        No systems assigned to this environment yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Versions Tab — placeholder */}
      {tab === 2 && (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">
            Versions will be available in a future update.
          </Typography>
        </Paper>
      )}

      {/* Add / Edit System Dialog */}
      <Dialog open={sysDialogOpen} onClose={() => setSysDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{sysEditTarget ? 'Edit System in Environment' : 'Add System'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {sysFormError && <Alert severity="error">{sysFormError}</Alert>}

          {!sysEditTarget && (
            <FormControl fullWidth required>
              <InputLabel>System</InputLabel>
              <Select
                label="System"
                value={sysForm.system_id}
                onChange={(e) => setSysForm({ ...sysForm, system_id: e.target.value as number })}
              >
                {availableSystems.length === 0 ? (
                  <MenuItem disabled value="">
                    No available systems
                  </MenuItem>
                ) : (
                  availableSystems.map((s) => (
                    <MenuItem key={s.id} value={s.id}>
                      {s.name}
                    </MenuItem>
                  ))
                )}
              </Select>
            </FormControl>
          )}

          <FormControl fullWidth>
            <InputLabel>Status</InputLabel>
            <Select
              label="Status"
              value={sysForm.status}
              onChange={(e) =>
                setSysForm({ ...sysForm, status: e.target.value as EnvironmentSystemStatus })
              }
            >
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="inactive">Inactive</MenuItem>
              <MenuItem value="mock">Mock</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label="Mock Notes"
            value={sysForm.mock_notes}
            onChange={(e) => setSysForm({ ...sysForm, mock_notes: e.target.value })}
            fullWidth
            multiline
            rows={2}
            placeholder="Notes about mock behaviour (optional)"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSysDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSysSave} variant="contained" disabled={loading}>
            {sysEditTarget ? 'Save' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Remove System Confirmation */}
      <Dialog open={Boolean(sysDeleteTarget)} onClose={() => setSysDeleteTarget(null)}>
        <DialogTitle>Remove System</DialogTitle>
        <DialogContent>
          <Typography>
            Remove <strong>{sysDeleteTarget?.system.name}</strong> from this environment?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSysDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleSysDelete} color="error" variant="contained">
            Remove
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
