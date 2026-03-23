import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  MenuItem,
  Paper,
  Select,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  FormControl,
  InputLabel,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchEnvironments,
  createEnvironment,
  updateEnvironment,
  deleteEnvironment,
} from '../../store/environmentSlice';
import type {
  EnvironmentResponse,
  EnvironmentStatus,
  EnvironmentCreate,
  EnvironmentUpdate,
} from '../../types/environment';

const STATUS_COLORS: Record<EnvironmentStatus, 'success' | 'warning' | 'default' | 'error'> = {
  active: 'success',
  maintenance: 'warning',
  inactive: 'default',
  decommissioned: 'error',
};

const STATUS_FILTERS: { label: string; value: EnvironmentStatus | 'all' }[] = [
  { label: 'All', value: 'all' },
  { label: 'Active', value: 'active' },
  { label: 'Inactive', value: 'inactive' },
  { label: 'Maintenance', value: 'maintenance' },
  { label: 'Decommissioned', value: 'decommissioned' },
];

interface EnvFormValues {
  name: string;
  description: string;
  environment_type: string;
  status: EnvironmentStatus;
}

const emptyForm: EnvFormValues = {
  name: '',
  description: '',
  environment_type: '',
  status: 'active',
};

export default function EnvironmentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { environments, loading, error } = useSelector((state: RootState) => state.environment);

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<EnvironmentStatus | 'all'>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EnvironmentResponse | null>(null);
  const [form, setForm] = useState<EnvFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<EnvironmentResponse | null>(null);

  useEffect(() => {
    dispatch(fetchEnvironments());
  }, [dispatch]);

  const filtered = environments.filter((e) => {
    const matchesSearch = e.name.toLowerCase().includes(search.toLowerCase());
    const matchesStatus = statusFilter === 'all' || e.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const openCreate = () => {
    setEditTarget(null);
    setForm(emptyForm);
    setFormError('');
    setDialogOpen(true);
  };

  const openEdit = (env: EnvironmentResponse) => {
    setEditTarget(env);
    setForm({
      name: env.name,
      description: env.description ?? '',
      environment_type: env.environment_type,
      status: env.status,
    });
    setFormError('');
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Name is required');
      return;
    }
    if (!form.environment_type.trim()) {
      setFormError('Environment type is required');
      return;
    }
    try {
      if (editTarget) {
        const data: EnvironmentUpdate = {
          name: form.name,
          description: form.description || undefined,
          environment_type: form.environment_type,
          status: form.status,
        };
        await dispatch(updateEnvironment({ id: editTarget.id, data })).unwrap();
      } else {
        const data: EnvironmentCreate = {
          name: form.name,
          description: form.description || undefined,
          environment_type: form.environment_type,
          status: form.status,
        };
        await dispatch(createEnvironment(data)).unwrap();
      }
      setDialogOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setFormError(message || 'Failed to save environment');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await dispatch(deleteEnvironment(deleteTarget.id)).unwrap();
    } finally {
      setDeleteTarget(null);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      {/* Header row */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          Environments
        </Typography>
        <TextField
          size="small"
          placeholder="Search environments…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          New Environment
        </Button>
      </Box>

      {/* Status filter chips */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {STATUS_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            color={statusFilter === f.value ? 'primary' : 'default'}
            variant={statusFilter === f.value ? 'filled' : 'outlined'}
            onClick={() => setStatusFilter(f.value)}
          />
        ))}
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Type</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Created</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && environments.length === 0
              ? Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 5 }).map((__, j) => (
                      <TableCell key={j}><Skeleton /></TableCell>
                    ))}
                  </TableRow>
                ))
              : filtered.map((env) => (
                  <TableRow
                    key={env.id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/environments/${env.id}`)}
                  >
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {env.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {env.environment_type}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={env.status}
                        size="small"
                        color={STATUS_COLORS[env.status]}
                      />
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {new Date(env.created_at).toLocaleDateString()}
                      </Typography>
                    </TableCell>
                    <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openEdit(env)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setDeleteTarget(env)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
            {!loading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} align="center">
                  <Typography color="text.secondary" py={3}>
                    {search || statusFilter !== 'all'
                      ? 'No environments match your filter.'
                      : 'No environments yet. Create one!'}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editTarget ? 'Edit Environment' : 'New Environment'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {formError && <Alert severity="error">{formError}</Alert>}
          <TextField
            label="Name"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            fullWidth
          />
          <TextField
            label="Description"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            fullWidth
            multiline
            rows={2}
          />
          <TextField
            label="Environment Type"
            required
            value={form.environment_type}
            onChange={(e) => setForm({ ...form, environment_type: e.target.value })}
            fullWidth
            placeholder="e.g. staging, uat, dev"
          />
          <FormControl fullWidth>
            <InputLabel>Status</InputLabel>
            <Select
              label="Status"
              value={form.status}
              onChange={(e) => setForm({ ...form, status: e.target.value as EnvironmentStatus })}
            >
              <MenuItem value="active">Active</MenuItem>
              <MenuItem value="inactive">Inactive</MenuItem>
              <MenuItem value="maintenance">Maintenance</MenuItem>
              <MenuItem value="decommissioned">Decommissioned</MenuItem>
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSave} variant="contained" disabled={loading}>
            {editTarget ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete Environment</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{deleteTarget?.name}</strong>?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
