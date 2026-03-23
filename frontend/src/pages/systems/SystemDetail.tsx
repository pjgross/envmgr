import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Paper,
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
} from '../../store/systemSlice';
import type {
  SystemUpdate,
  SubSystemResponse,
  SubSystemCreate,
  SubSystemUpdate,
} from '../../types/system';

interface SubFormValues {
  name: string;
  description: string;
}

const emptySubForm: SubFormValues = { name: '', description: '' };

export default function SystemDetail() {
  const { id } = useParams<{ id: string }>();
  const systemId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  const { currentSystem, subsystems, loading, error } = useSelector(
    (state: RootState) => state.system
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

  useEffect(() => {
    dispatch(fetchSystem(systemId));
    dispatch(fetchSubSystems(systemId));
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
    </Box>
  );
}
