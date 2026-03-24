import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
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
import CheckCircleIcon from '@mui/icons-material/CheckCircle';

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
import { verifyEnvironment, clearVerifyResult } from '../../store/dependencySlice';
import { fetchVersions, recordVersion, clearVersions, updateVersion, deleteVersion } from '../../store/versionSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { systemService } from '../../services/systemService';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';
import type {
  EnvironmentUpdate,
  EnvironmentStatus,
  EnvironmentSystemResponse,
  EnvironmentSystemCreate,
  EnvironmentSystemUpdate,
  EnvironmentSystemStatus,
} from '../../types/environment';
import type { VersionCreate, VersionUpdate, VersionResponse } from '../../types/version';
import type { SubSystemResponse } from '../../types/system';

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
  const { verifyResult, loading: verifyLoading } = useSelector(
    (state: RootState) => state.dependency
  );
  const { versions, loading: versionsLoading } = useSelector(
    (state: RootState) => state.version
  );
  const envCustomFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['environment'] ?? []
  );
  const user = useSelector((state: RootState) => state.auth.user);

  const [tab, setTab] = useState(0);

  // Overview edit state
  const [editMode, setEditMode] = useState(false);
  const [envCustomFieldValues, setEnvCustomFieldValues] = useState<Record<string, unknown>>({});
  const [envForm, setEnvForm] = useState<EnvFormValues>({
    name: '',
    description: '',
    environment_type: '',
    status: 'active',
  });
  const [envFormError, setEnvFormError] = useState('');

  // Version tab state
  const [versionCurrentOnly, setVersionCurrentOnly] = useState(false);
  const [versionDialogOpen, setVersionDialogOpen] = useState(false);
  const [versionForm, setVersionForm] = useState<VersionCreate>({
    subsystem_id: 0,
    build_id: '',
    version_label: '',
    installed_at: undefined,
  });
  const [versionFormError, setVersionFormError] = useState('');
  const [availableSubsystems, setAvailableSubsystems] = useState<(SubSystemResponse & { systemName: string })[]>([]);

  // Version edit state
  const [editVersionTarget, setEditVersionTarget] = useState<VersionResponse | null>(null);
  const [editVersionForm, setEditVersionForm] = useState<{ build_id: string; version_label: string; installed_at: string }>({ build_id: '', version_label: '', installed_at: '' });
  const [editVersionError, setEditVersionError] = useState('');

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
    dispatch(fetchDefinitions('environment'));
    // Clear any previous verify result when env changes
    dispatch(clearVerifyResult());
  }, [dispatch, envId]);

  useEffect(() => {
    if (currentEnvironment) {
      setEnvForm({
        name: currentEnvironment.name,
        description: currentEnvironment.description ?? '',
        environment_type: currentEnvironment.environment_type,
        status: currentEnvironment.status,
      });
      setEnvCustomFieldValues(currentEnvironment.custom_fields ?? {});
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
        custom_fields: envCustomFieldValues,
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

  const handleVerify = () => {
    dispatch(verifyEnvironment(envId));
  };

  const handleTabChange = (_: React.SyntheticEvent, newValue: number) => {
    setTab(newValue);
    if (newValue === 2) {
      // Lazy-load versions when tab is first opened
      dispatch(clearVersions());
      dispatch(fetchVersions({ envId, currentOnly: versionCurrentOnly }));
    }
  };

  const handleVersionToggle = (currentOnly: boolean) => {
    setVersionCurrentOnly(currentOnly);
    dispatch(fetchVersions({ envId, currentOnly }));
  };

  const openVersionDialog = async () => {
    setVersionForm({ subsystem_id: 0, build_id: '', version_label: '', installed_at: undefined });
    setVersionFormError('');
    // Fetch subsystems for all assigned systems
    const allSubsystems: (SubSystemResponse & { systemName: string })[] = [];
    for (const envSys of environmentSystems) {
      try {
        const subs = await systemService.listSubSystems(envSys.system_id);
        for (const sub of subs) {
          allSubsystems.push({ ...sub, systemName: envSys.system.name });
        }
      } catch {
        // ignore fetch errors per system
      }
    }
    setAvailableSubsystems(allSubsystems);
    setVersionDialogOpen(true);
  };

  const handleVersionSave = async () => {
    if (!versionForm.subsystem_id) {
      setVersionFormError('Please select a subsystem');
      return;
    }
    if (!versionForm.build_id.trim()) {
      setVersionFormError('Build ID is required');
      return;
    }
    if (!versionForm.version_label.trim()) {
      setVersionFormError('Version Label is required');
      return;
    }
    try {
      await dispatch(recordVersion({ envId, data: versionForm })).unwrap();
      setVersionDialogOpen(false);
      setVersionForm({ subsystem_id: 0, build_id: '', version_label: '', installed_at: undefined });
      setVersionFormError('');
      // Refresh versions list
      dispatch(fetchVersions({ envId, currentOnly: versionCurrentOnly }));
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setVersionFormError(message || 'Failed to record version');
    }
  };

  const openEditVersion = (v: VersionResponse) => {
    setEditVersionTarget(v);
    setEditVersionForm({
      build_id: v.build_id,
      version_label: v.version_label,
      installed_at: v.installed_at ? new Date(v.installed_at).toISOString().slice(0, 16) : '',
    });
    setEditVersionError('');
  };

  const handleEditVersionSave = async () => {
    if (!editVersionTarget || !currentEnvironment) return;
    const data: VersionUpdate = {};
    if (editVersionForm.build_id) data.build_id = editVersionForm.build_id;
    if (editVersionForm.version_label) data.version_label = editVersionForm.version_label;
    if (editVersionForm.installed_at) data.installed_at = new Date(editVersionForm.installed_at).toISOString();
    try {
      await dispatch(updateVersion({ envId: currentEnvironment.id, versionId: editVersionTarget.id, data })).unwrap();
      setEditVersionTarget(null);
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message;
      setEditVersionError(msg ?? 'Failed to save changes');
    }
  };

  const handleDeleteVersion = async (versionId: number) => {
    if (!currentEnvironment) return;
    if (!window.confirm('Delete this version record? This cannot be undone.')) return;
    try {
      await dispatch(deleteVersion({ envId: currentEnvironment.id, versionId })).unwrap();
    } catch (e: unknown) {
      alert('Failed to delete version. Please try again.');
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

  // Flatten all dependency items from verify result for the missing table
  const allDepItems = verifyResult
    ? verifyResult.systems.flatMap((s) =>
        s.dependencies.map((d) => ({ ...d, system_name: s.system_name }))
      )
    : [];
  const nonSatisfiedItems = allDepItems.filter((d) => d.status !== 'satisfied');

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

      <Tabs value={tab} onChange={handleTabChange} sx={{ mb: 2 }}>
        <Tab label="Overview" />
        <Tab label="Systems" />
        <Tab label="Versions" />
      </Tabs>

      {/* Overview Tab */}
      {tab === 0 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
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
                {envCustomFieldDefs.length > 0 && (
                  <CustomFieldsSection
                    definitions={envCustomFieldDefs}
                    values={envCustomFieldValues}
                    onChange={setEnvCustomFieldValues}
                  />
                )}
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
                {envCustomFieldDefs.length > 0 && (
                  <>
                    <Divider sx={{ my: 1 }} />
                    <CustomFieldsDisplay
                      definitions={envCustomFieldDefs}
                      values={currentEnvironment?.custom_fields}
                    />
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

          {/* Verify Environment Panel */}
          {!editMode && (
            <Paper sx={{ p: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Typography variant="h6">Dependency Verification</Typography>
                <Button
                  variant="outlined"
                  startIcon={verifyLoading ? <CircularProgress size={16} /> : <CheckCircleIcon />}
                  onClick={handleVerify}
                  disabled={verifyLoading}
                >
                  Verify Environment
                </Button>
              </Box>

              {verifyResult && (
                <>
                  {verifyResult.total_dependencies === 0 ? (
                    <Alert severity="info">No dependencies declared for systems in this environment.</Alert>
                  ) : verifyResult.missing_count === 0 && verifyResult.mocked_count === 0 ? (
                    <Alert severity="success">All dependencies satisfied.</Alert>
                  ) : (
                    <>
                      <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                        <Chip
                          label={`${verifyResult.satisfied_count} satisfied`}
                          color="success"
                          size="small"
                        />
                        <Chip
                          label={`${verifyResult.mocked_count} mocked`}
                          color="warning"
                          size="small"
                        />
                        <Chip
                          label={`${verifyResult.missing_count} missing`}
                          color="error"
                          size="small"
                        />
                      </Box>

                      {nonSatisfiedItems.length > 0 && (
                        <TableContainer>
                          <Table size="small">
                            <TableHead>
                              <TableRow>
                                <TableCell>System</TableCell>
                                <TableCell>Depends On</TableCell>
                                <TableCell>Type</TableCell>
                                <TableCell>Status</TableCell>
                              </TableRow>
                            </TableHead>
                            <TableBody>
                              {nonSatisfiedItems.map((item) => (
                                <TableRow key={`${item.system_name}-${item.to_system_id}`}>
                                  <TableCell>{item.system_name}</TableCell>
                                  <TableCell>{item.to_system_name}</TableCell>
                                  <TableCell>
                                    <Chip
                                      label={item.dependency_type.replace(/_/g, ' ')}
                                      size="small"
                                      variant="outlined"
                                    />
                                  </TableCell>
                                  <TableCell>
                                    <Chip
                                      label={item.status}
                                      size="small"
                                      color={item.status === 'missing' ? 'error' : 'warning'}
                                    />
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </TableContainer>
                      )}
                    </>
                  )}
                </>
              )}
            </Paper>
          )}
        </Box>
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

      {/* Versions Tab */}
      {tab === 2 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                variant={versionCurrentOnly ? 'outlined' : 'contained'}
                size="small"
                onClick={() => handleVersionToggle(false)}
              >
                All History
              </Button>
              <Button
                variant={versionCurrentOnly ? 'contained' : 'outlined'}
                size="small"
                onClick={() => handleVersionToggle(true)}
              >
                Current
              </Button>
            </Box>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={openVersionDialog}
            >
              Record Version
            </Button>
          </Box>

          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>SubSystem</TableCell>
                  <TableCell>Build ID</TableCell>
                  <TableCell>Version Label</TableCell>
                  <TableCell>Installed At</TableCell>
                  {user?.role === 'Admin' && <TableCell align="right">Actions</TableCell>}
                </TableRow>
              </TableHead>
              <TableBody>
                {versionsLoading ? (
                  <TableRow>
                    <TableCell colSpan={user?.role === 'Admin' ? 5 : 4} align="center">
                      <CircularProgress size={24} />
                    </TableCell>
                  </TableRow>
                ) : versions.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={user?.role === 'Admin' ? 5 : 4} align="center">
                      <Typography color="text.secondary" py={3}>
                        No version history recorded yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  versions.map((v) => (
                    <TableRow key={v.id} hover>
                      <TableCell>{v.subsystem_name}</TableCell>
                      <TableCell>{v.build_id}</TableCell>
                      <TableCell>{v.version_label}</TableCell>
                      <TableCell>
                        {new Date(v.installed_at).toLocaleString()}
                      </TableCell>
                      {user?.role === 'Admin' && (
                        <TableCell align="right" sx={{ whiteSpace: 'nowrap' }}>
                          <Tooltip title="Edit">
                            <IconButton size="small" onClick={() => openEditVersion(v)}><EditIcon fontSize="small" /></IconButton>
                          </Tooltip>
                          <Tooltip title="Delete">
                            <IconButton size="small" color="error" onClick={() => handleDeleteVersion(v.id)}><DeleteIcon fontSize="small" /></IconButton>
                          </Tooltip>
                        </TableCell>
                      )}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Edit Version Dialog */}
      <Dialog open={editVersionTarget !== null} onClose={() => setEditVersionTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Version</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '32px' }}>
          {editVersionError && <Alert severity="error" sx={{ mx: 2 }}>{editVersionError}</Alert>}
          <TextField
            label="Build ID *"
            value={editVersionForm.build_id}
            onChange={(e) => setEditVersionForm((f) => ({ ...f, build_id: e.target.value }))}
            fullWidth
          />
          <TextField
            label="Version Label *"
            value={editVersionForm.version_label}
            onChange={(e) => setEditVersionForm((f) => ({ ...f, version_label: e.target.value }))}
            fullWidth
          />
          <TextField
            label="Installed At"
            type="datetime-local"
            value={editVersionForm.installed_at}
            onChange={(e) => setEditVersionForm((f) => ({ ...f, installed_at: e.target.value }))}
            fullWidth
            InputLabelProps={{ shrink: true }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditVersionTarget(null)}>Cancel</Button>
          <Button
            onClick={handleEditVersionSave}
            variant="contained"
            disabled={!editVersionForm.build_id || !editVersionForm.version_label}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Record Version Dialog */}
      <Dialog open={versionDialogOpen} onClose={() => setVersionDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Record Version</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '32px' }}>
          {versionFormError && <Alert severity="error">{versionFormError}</Alert>}
          <FormControl fullWidth required>
            <InputLabel>SubSystem</InputLabel>
            <Select
              label="SubSystem"
              value={versionForm.subsystem_id || ''}
              onChange={(e) =>
                setVersionForm({ ...versionForm, subsystem_id: e.target.value as number })
              }
            >
              {availableSubsystems.length === 0 ? (
                <MenuItem disabled value="">
                  No subsystems available (add systems with subsystems first)
                </MenuItem>
              ) : (
                availableSubsystems.map((sub) => (
                  <MenuItem key={sub.id} value={sub.id}>
                    {sub.systemName} / {sub.name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          <TextField
            label="Build ID"
            required
            value={versionForm.build_id}
            onChange={(e) => setVersionForm({ ...versionForm, build_id: e.target.value })}
            fullWidth
            placeholder="e.g. build-1234"
          />
          <TextField
            label="Version Label"
            required
            value={versionForm.version_label}
            onChange={(e) => setVersionForm({ ...versionForm, version_label: e.target.value })}
            fullWidth
            placeholder="e.g. v2.1.0"
          />
          <TextField
            label="Installed At (optional)"
            type="datetime-local"
            value={versionForm.installed_at ?? ''}
            onChange={(e) =>
              setVersionForm({
                ...versionForm,
                installed_at: e.target.value ? new Date(e.target.value).toISOString() : undefined,
              })
            }
            fullWidth
            InputLabelProps={{ shrink: true }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVersionDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleVersionSave} variant="contained" disabled={versionsLoading}>
            Record
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add / Edit System Dialog */}
      <Dialog open={sysDialogOpen} onClose={() => setSysDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{sysEditTarget ? 'Edit System in Environment' : 'Add System'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '32px' }}>
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
