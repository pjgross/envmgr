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
  Link,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchSystem,
  updateSystem,
  fetchSubSystems,
  createSubSystem,
  updateSubSystem,
  deleteSubSystem,
  fetchSystems,
} from '../../store/systemSlice';
import {
  fetchSystemDependencies,
  createSystemDependency,
  deleteSystemDependency,
  fetchComponentDependencies,
  createComponentDependency,
  deleteComponentDependency,
} from '../../store/dependencySlice';
import { dependencyService } from '../../services/dependencyService';
import type {
  SystemUpdate,
  SubSystemResponse,
  SubSystemCreate,
  SubSystemUpdate,
} from '../../types/system';
import type {
  DependencyType,
  DependencyDirection,
  SystemDependencyResponse,
  ComponentDependencyResponse,
  ComponentDependencyCreate,
} from '../../types/dependency';

const DEP_TYPE_OPTIONS: { value: DependencyType; label: string }[] = [
  { value: 'api_call', label: 'API Call' },
  { value: 'database', label: 'Database' },
  { value: 'message_queue', label: 'Message Queue' },
  { value: 'event', label: 'Event' },
  { value: 'file', label: 'File' },
  { value: 'other', label: 'Other' },
];

const DEP_DIRECTION_OPTIONS: { value: DependencyDirection; label: string }[] = [
  { value: 'one_way', label: 'One-way' },
  { value: 'two_way', label: 'Two-way' },
];

interface SubFormValues {
  name: string;
  description: string;
}

const emptySubForm: SubFormValues = { name: '', description: '' };

interface DepFormValues {
  to_system_id: number | '';
  dependency_type: DependencyType;
  direction: DependencyDirection;
}

const emptyDepForm: DepFormValues = {
  to_system_id: '',
  dependency_type: 'api_call',
  direction: 'one_way',
};

interface AllSubsystem {
  id: number;
  name: string;
  system_id: number;
  system_name: string;
}

interface CompDepFormValues {
  from_subsystem_id: number | '';
  to_subsystem_id: number | '';
  dependency_type: DependencyType;
  direction: DependencyDirection;
}

const emptyCompDepForm: CompDepFormValues = {
  from_subsystem_id: '',
  to_subsystem_id: '',
  dependency_type: 'api_call',
  direction: 'one_way',
};

export default function SystemDetail() {
  const { id } = useParams<{ id: string }>();
  const systemId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const { currentSystem, subsystems, systems, loading, error } = useSelector(
    (state: RootState) => state.system
  );
  const { systemDependencies, componentDependencies, loading: depLoading } = useSelector(
    (state: RootState) => state.dependency
  );

  const [tab, setTab] = useState(0);

  // Overview edit state
  const [editMode, setEditMode] = useState(false);
  const [sysForm, setSysForm] = useState({ name: '', description: '', github_repository_url: '' });
  const [sysFormError, setSysFormError] = useState('');

  // SubSystem dialog state
  const [subDialogOpen, setSubDialogOpen] = useState(false);
  const [subEditTarget, setSubEditTarget] = useState<SubSystemResponse | null>(null);
  const [subForm, setSubForm] = useState<SubFormValues>(emptySubForm);
  const [subFormError, setSubFormError] = useState('');
  const [subDeleteTarget, setSubDeleteTarget] = useState<SubSystemResponse | null>(null);

  // System dependency dialog state
  const [depDialogOpen, setDepDialogOpen] = useState(false);
  const [depForm, setDepForm] = useState<DepFormValues>(emptyDepForm);
  const [depFormError, setDepFormError] = useState('');
  const [depDeleteTarget, setDepDeleteTarget] = useState<SystemDependencyResponse | null>(null);

  // Component dependency state
  const [compDepDialogOpen, setCompDepDialogOpen] = useState(false);
  const [compDepForm, setCompDepForm] = useState<CompDepFormValues>(emptyCompDepForm);
  const [compDepFormError, setCompDepFormError] = useState('');
  const [compDepDeleteTarget, setCompDepDeleteTarget] = useState<ComponentDependencyResponse | null>(null);
  const [allSubsystems, setAllSubsystems] = useState<AllSubsystem[]>([]);
  const [allSubsystemsLoading, setAllSubsystemsLoading] = useState(false);
  // Component deps merged across all subsystems of this system
  const [allCompDeps, setAllCompDeps] = useState<ComponentDependencyResponse[]>([]);
  const [compDepsLoading, setCompDepsLoading] = useState(false);

  useEffect(() => {
    dispatch(fetchSystem(systemId));
    dispatch(fetchSubSystems(systemId));
    dispatch(fetchSystemDependencies(systemId));
    dispatch(fetchSystems());
  }, [dispatch, systemId]);

  useEffect(() => {
    if (currentSystem) {
      setSysForm({
        name: currentSystem.name,
        description: currentSystem.description ?? '',
        github_repository_url: currentSystem.github_repository_url ?? '',
      });
    }
  }, [currentSystem]);

  // Load component deps for all subsystems of this system when on tab 3
  useEffect(() => {
    if (tab !== 3 || subsystems.length === 0) return;
    const loadCompDeps = async () => {
      setCompDepsLoading(true);
      try {
        const results = await Promise.all(
          subsystems.map((sub) =>
            dependencyService.listComponentDependencies(sub.id).catch(() => [])
          )
        );
        // Merge and deduplicate by id
        const seen = new Set<number>();
        const merged: ComponentDependencyResponse[] = [];
        for (const list of results) {
          for (const dep of list) {
            if (!seen.has(dep.id)) {
              seen.add(dep.id);
              merged.push(dep);
            }
          }
        }
        setAllCompDeps(merged);
      } finally {
        setCompDepsLoading(false);
      }
    };
    loadCompDeps();
  }, [tab, subsystems]);

  const handleSysUpdate = async () => {
    if (!sysForm.name.trim()) {
      setSysFormError('Name is required');
      return;
    }
    try {
      const data: SystemUpdate = {
        name: sysForm.name,
        description: sysForm.description || undefined,
        github_repository_url: sysForm.github_repository_url || undefined,
      };
      await dispatch(updateSystem({ id: systemId, data })).unwrap();
      setEditMode(false);
      setSysFormError('');
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSysFormError(message || 'Failed to update');
    }
  };

  const openSubCreate = () => {
    setSubEditTarget(null);
    setSubForm(emptySubForm);
    setSubFormError('');
    setSubDialogOpen(true);
  };

  const openSubEdit = (sub: SubSystemResponse) => {
    setSubEditTarget(sub);
    setSubForm({ name: sub.name, description: sub.description ?? '' });
    setSubFormError('');
    setSubDialogOpen(true);
  };

  const handleSubSave = async () => {
    if (!subForm.name.trim()) {
      setSubFormError('Name is required');
      return;
    }
    try {
      if (subEditTarget) {
        const data: SubSystemUpdate = {
          name: subForm.name,
          description: subForm.description || undefined,
        };
        await dispatch(
          updateSubSystem({ systemId, subId: subEditTarget.id, data })
        ).unwrap();
      } else {
        const data: SubSystemCreate = {
          name: subForm.name,
          description: subForm.description || undefined,
        };
        await dispatch(createSubSystem({ systemId, data })).unwrap();
      }
      setSubDialogOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setSubFormError(message || 'Failed to save subsystem');
    }
  };

  const handleSubDelete = async () => {
    if (!subDeleteTarget) return;
    try {
      await dispatch(deleteSubSystem({ systemId, subId: subDeleteTarget.id })).unwrap();
    } finally {
      setSubDeleteTarget(null);
    }
  };

  // System Dependency handlers
  const openDepCreate = () => {
    setDepForm(emptyDepForm);
    setDepFormError('');
    setDepDialogOpen(true);
  };

  const handleDepSave = async () => {
    if (!depForm.to_system_id) {
      setDepFormError('Please select a target system');
      return;
    }
    try {
      await dispatch(
        createSystemDependency({
          systemId,
          data: {
            to_system_id: depForm.to_system_id as number,
            dependency_type: depForm.dependency_type,
            direction: depForm.direction,
          },
        })
      ).unwrap();
      setDepDialogOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setDepFormError(message || 'Failed to create dependency');
    }
  };

  const handleDepDelete = async () => {
    if (!depDeleteTarget) return;
    try {
      await dispatch(
        deleteSystemDependency({ systemId, depId: depDeleteTarget.id })
      ).unwrap();
    } finally {
      setDepDeleteTarget(null);
    }
  };

  // Component Dependency handlers
  const openCompDepCreate = async () => {
    setCompDepForm(emptyCompDepForm);
    setCompDepFormError('');
    setCompDepDialogOpen(true);
    // Load all subsystems from all systems
    setAllSubsystemsLoading(true);
    try {
      const allSystems = systems.length > 0 ? systems : [];
      const results = await Promise.all(
        allSystems.map(async (sys) => {
          try {
            const resp = await fetch(`/api/v1/systems/${sys.id}/subsystems`, {
              headers: { Authorization: `Bearer ${localStorage.getItem('token') ?? ''}` },
            });
            if (!resp.ok) return [];
            const subs = await resp.json();
            return (subs as Array<{ id: number; name: string; system_id: number }>).map((sub) => ({
              id: sub.id,
              name: sub.name,
              system_id: sys.id,
              system_name: sys.name,
            }));
          } catch {
            return [];
          }
        })
      );
      setAllSubsystems(results.flat());
    } finally {
      setAllSubsystemsLoading(false);
    }
  };

  const handleCompDepSave = async () => {
    if (!compDepForm.from_subsystem_id) {
      setCompDepFormError('Please select a source subsystem');
      return;
    }
    if (!compDepForm.to_subsystem_id) {
      setCompDepFormError('Please select a target subsystem');
      return;
    }
    try {
      const data: ComponentDependencyCreate = {
        to_subsystem_id: compDepForm.to_subsystem_id as number,
        dependency_type: compDepForm.dependency_type,
        direction: compDepForm.direction,
      };
      await dispatch(
        createComponentDependency({
          subsystemId: compDepForm.from_subsystem_id as number,
          data,
        })
      ).unwrap();
      setCompDepDialogOpen(false);
      // Refresh merged list
      setTab(3);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setCompDepFormError(message || 'Failed to create component dependency');
    }
  };

  const handleCompDepDelete = async () => {
    if (!compDepDeleteTarget) return;
    try {
      // Use from_subsystem_id as the context for deletion
      const subsystemId = compDepDeleteTarget.from_subsystem_id;
      await dispatch(
        deleteComponentDependency({ subsystemId, depId: compDepDeleteTarget.id })
      ).unwrap();
      // Remove from local list
      setAllCompDeps((prev) => prev.filter((d) => d.id !== compDepDeleteTarget.id));
    } finally {
      setCompDepDeleteTarget(null);
    }
  };

  // Systems available for outgoing dependency (exclude self and already outgoing targets)
  const outgoingDepTargetIds = new Set(
    systemDependencies.filter((d) => !d.is_incoming).map((d) => d.to_system_id)
  );
  const availableForDep = systems.filter(
    (s) => s.id !== systemId && !outgoingDepTargetIds.has(s.id)
  );

  if (loading && !currentSystem) {
    return (
      <Box sx={{ p: 3 }}>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (error && !currentSystem) {
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
        <IconButton onClick={() => navigate('/systems')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          {currentSystem?.name ?? '…'}
        </Typography>
        {!editMode && tab === 0 && (
          <Button startIcon={<EditIcon />} onClick={() => setEditMode(true)}>
            Edit
          </Button>
        )}
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Overview" />
        <Tab label="SubSystems" />
        <Tab label="Dependencies" />
        <Tab label="Component Deps" />
      </Tabs>

      {/* Overview Tab */}
      {tab === 0 && (
        <Paper sx={{ p: 3 }}>
          {editMode ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {sysFormError && <Alert severity="error">{sysFormError}</Alert>}
              <TextField
                label="Name"
                required
                value={sysForm.name}
                onChange={(e) => setSysForm({ ...sysForm, name: e.target.value })}
              />
              <TextField
                label="Description"
                value={sysForm.description}
                onChange={(e) => setSysForm({ ...sysForm, description: e.target.value })}
                multiline
                rows={3}
              />
              <TextField
                label="GitHub Repository URL"
                value={sysForm.github_repository_url}
                onChange={(e) =>
                  setSysForm({ ...sysForm, github_repository_url: e.target.value })
                }
                placeholder="https://github.com/org/repo"
              />
              <Box sx={{ display: 'flex', gap: 1 }}>
                <Button variant="contained" onClick={handleSysUpdate} disabled={loading}>
                  Save
                </Button>
                <Button onClick={() => setEditMode(false)}>Cancel</Button>
              </Box>
            </Box>
          ) : (
            <Box>
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">
                  Name
                </Typography>
                <Typography>{currentSystem?.name}</Typography>
              </Box>
              <Divider sx={{ my: 1 }} />
              <Box sx={{ mb: 2 }}>
                <Typography variant="overline" color="text.secondary">
                  Description
                </Typography>
                <Typography>{currentSystem?.description ?? '—'}</Typography>
              </Box>
              <Divider sx={{ my: 1 }} />
              <Box>
                <Typography variant="overline" color="text.secondary">
                  GitHub Repository
                </Typography>
                <Typography>
                  {currentSystem?.github_repository_url ? (
                    <Link
                      href={currentSystem.github_repository_url}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {currentSystem.github_repository_url}
                    </Link>
                  ) : (
                    '—'
                  )}
                </Typography>
              </Box>
            </Box>
          )}
        </Paper>
      )}

      {/* SubSystems Tab */}
      {tab === 1 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openSubCreate}>
              Add SubSystem
            </Button>
          </Box>

          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Description</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {subsystems.map((sub) => (
                  <TableRow key={sub.id} hover>
                    <TableCell>{sub.name}</TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {sub.description ?? '—'}
                      </Typography>
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openSubEdit(sub)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setSubDeleteTarget(sub)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
                {subsystems.length === 0 && !loading && (
                  <TableRow>
                    <TableCell colSpan={3} align="center">
                      <Typography color="text.secondary" py={3}>
                        No subsystems yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Dependencies Tab */}
      {tab === 2 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openDepCreate}>
              Add Dependency
            </Button>
          </Box>

          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Direction</TableCell>
                  <TableCell>Target / Source System</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Direction Type</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {systemDependencies.map((dep) => (
                  <TableRow key={dep.id} hover>
                    <TableCell>
                      <Chip
                        label={dep.is_incoming ? '← incoming' : '→ outgoing'}
                        size="small"
                        color={dep.is_incoming ? 'info' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {dep.is_incoming
                          ? (dep.from_system?.name ?? `System #${dep.from_system_id}`)
                          : dep.to_system.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={dep.dependency_type.replace(/_/g, ' ')}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={dep.direction === 'two_way' ? 'Two-way' : 'One-way'}
                        size="small"
                        color={dep.direction === 'two_way' ? 'secondary' : 'default'}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setDepDeleteTarget(dep)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
                {systemDependencies.length === 0 && !depLoading && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      <Typography color="text.secondary" py={3}>
                        No dependencies declared.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* Component Dependencies Tab */}
      {tab === 3 && (
        <Box>
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 2 }}>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCompDepCreate}>
              Add Component Dependency
            </Button>
          </Box>

          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>From SubSystem</TableCell>
                  <TableCell>To SubSystem</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Direction</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {compDepsLoading ? (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      <Typography color="text.secondary" py={3}>
                        Loading…
                      </Typography>
                    </TableCell>
                  </TableRow>
                ) : (
                  <>
                    {allCompDeps.map((dep) => (
                      <TableRow key={dep.id} hover>
                        <TableCell>
                          <Typography variant="body2">
                            {dep.from_subsystem?.name ?? `SubSystem #${dep.from_subsystem_id}`}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2">
                            {dep.to_subsystem.name}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={dep.dependency_type.replace(/_/g, ' ')}
                            size="small"
                            variant="outlined"
                          />
                        </TableCell>
                        <TableCell>
                          <Chip
                            label={dep.direction === 'two_way' ? 'Two-way' : 'One-way'}
                            size="small"
                            color={dep.direction === 'two_way' ? 'secondary' : 'default'}
                            variant="outlined"
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title="Delete">
                            <IconButton
                              size="small"
                              color="error"
                              onClick={() => setCompDepDeleteTarget(dep)}
                            >
                              <DeleteIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    ))}
                    {allCompDeps.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} align="center">
                          <Typography color="text.secondary" py={3}>
                            No component dependencies declared.
                          </Typography>
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Box>
      )}

      {/* SubSystem Create / Edit Dialog */}
      <Dialog open={subDialogOpen} onClose={() => setSubDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{subEditTarget ? 'Edit SubSystem' : 'Add SubSystem'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {subFormError && <Alert severity="error">{subFormError}</Alert>}
          <TextField
            label="Name"
            required
            value={subForm.name}
            onChange={(e) => setSubForm({ ...subForm, name: e.target.value })}
            fullWidth
          />
          <TextField
            label="Description"
            value={subForm.description}
            onChange={(e) => setSubForm({ ...subForm, description: e.target.value })}
            fullWidth
            multiline
            rows={2}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSubSave} variant="contained" disabled={loading}>
            {subEditTarget ? 'Save' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* SubSystem Delete Confirmation */}
      <Dialog open={Boolean(subDeleteTarget)} onClose={() => setSubDeleteTarget(null)}>
        <DialogTitle>Delete SubSystem</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{subDeleteTarget?.name}</strong>?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSubDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleSubDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add System Dependency Dialog */}
      <Dialog open={depDialogOpen} onClose={() => setDepDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Dependency</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {depFormError && <Alert severity="error">{depFormError}</Alert>}
          <FormControl fullWidth required>
            <InputLabel>Target System</InputLabel>
            <Select
              label="Target System"
              value={depForm.to_system_id}
              onChange={(e) =>
                setDepForm({ ...depForm, to_system_id: e.target.value as number })
              }
            >
              {availableForDep.length === 0 ? (
                <MenuItem disabled value="">
                  No available systems
                </MenuItem>
              ) : (
                availableForDep.map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    {s.name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>Dependency Type</InputLabel>
            <Select
              label="Dependency Type"
              value={depForm.dependency_type}
              onChange={(e) =>
                setDepForm({ ...depForm, dependency_type: e.target.value as DependencyType })
              }
            >
              {DEP_TYPE_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>Direction</InputLabel>
            <Select
              label="Direction"
              value={depForm.direction}
              onChange={(e) =>
                setDepForm({ ...depForm, direction: e.target.value as DependencyDirection })
              }
            >
              {DEP_DIRECTION_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDepDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleDepSave} variant="contained" disabled={depLoading}>
            Add
          </Button>
        </DialogActions>
      </Dialog>

      {/* System Dependency Delete Confirmation */}
      <Dialog open={Boolean(depDeleteTarget)} onClose={() => setDepDeleteTarget(null)}>
        <DialogTitle>Remove Dependency</DialogTitle>
        <DialogContent>
          <Typography>
            Remove dependency on{' '}
            <strong>
              {depDeleteTarget?.is_incoming
                ? (depDeleteTarget?.from_system?.name ?? `System #${depDeleteTarget?.from_system_id}`)
                : depDeleteTarget?.to_system.name}
            </strong>?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDepDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleDepDelete} color="error" variant="contained">
            Remove
          </Button>
        </DialogActions>
      </Dialog>

      {/* Add Component Dependency Dialog */}
      <Dialog open={compDepDialogOpen} onClose={() => setCompDepDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Add Component Dependency</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {compDepFormError && <Alert severity="error">{compDepFormError}</Alert>}
          <FormControl fullWidth required>
            <InputLabel>From SubSystem</InputLabel>
            <Select
              label="From SubSystem"
              value={compDepForm.from_subsystem_id}
              onChange={(e) =>
                setCompDepForm({ ...compDepForm, from_subsystem_id: e.target.value as number })
              }
            >
              {subsystems.length === 0 ? (
                <MenuItem disabled value="">
                  No subsystems available
                </MenuItem>
              ) : (
                subsystems.map((sub) => (
                  <MenuItem key={sub.id} value={sub.id}>
                    {sub.name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>To SubSystem</InputLabel>
            <Select
              label="To SubSystem"
              value={compDepForm.to_subsystem_id}
              onChange={(e) =>
                setCompDepForm({ ...compDepForm, to_subsystem_id: e.target.value as number })
              }
            >
              {allSubsystemsLoading ? (
                <MenuItem disabled value="">
                  Loading…
                </MenuItem>
              ) : allSubsystems.length === 0 ? (
                <MenuItem disabled value="">
                  No subsystems available
                </MenuItem>
              ) : (
                allSubsystems.map((sub) => (
                  <MenuItem key={sub.id} value={sub.id}>
                    {sub.system_name} / {sub.name}
                  </MenuItem>
                ))
              )}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>Dependency Type</InputLabel>
            <Select
              label="Dependency Type"
              value={compDepForm.dependency_type}
              onChange={(e) =>
                setCompDepForm({ ...compDepForm, dependency_type: e.target.value as DependencyType })
              }
            >
              {DEP_TYPE_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel>Direction</InputLabel>
            <Select
              label="Direction"
              value={compDepForm.direction}
              onChange={(e) =>
                setCompDepForm({ ...compDepForm, direction: e.target.value as DependencyDirection })
              }
            >
              {DEP_DIRECTION_OPTIONS.map((opt) => (
                <MenuItem key={opt.value} value={opt.value}>
                  {opt.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCompDepDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleCompDepSave} variant="contained" disabled={depLoading || allSubsystemsLoading}>
            Add
          </Button>
        </DialogActions>
      </Dialog>

      {/* Component Dependency Delete Confirmation */}
      <Dialog open={Boolean(compDepDeleteTarget)} onClose={() => setCompDepDeleteTarget(null)}>
        <DialogTitle>Remove Component Dependency</DialogTitle>
        <DialogContent>
          <Typography>
            Remove dependency from{' '}
            <strong>{compDepDeleteTarget?.from_subsystem?.name ?? `SubSystem #${compDepDeleteTarget?.from_subsystem_id}`}</strong>
            {' '}to{' '}
            <strong>{compDepDeleteTarget?.to_subsystem.name}</strong>?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCompDepDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleCompDepDelete} color="error" variant="contained">
            Remove
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
