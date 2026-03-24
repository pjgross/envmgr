import { useCallback, useEffect, useMemo, useState } from 'react';
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
  Select,
  TextField,
  Tooltip,
  Typography,
  FormControl,
  InputLabel,
} from '@mui/material';
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridValueGetterParams,
} from '@mui/x-data-grid';
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
import { fetchDefinitions } from '../../store/customFieldSlice';
import type {
  EnvironmentResponse,
  EnvironmentStatus,
  EnvironmentCreate,
  EnvironmentUpdate,
} from '../../types/environment';
import CustomFieldsSection from '../../components/CustomFieldsSection';

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

function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `environments-list-columns-${userId ?? 'guest'}`
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return {}
    return JSON.parse(raw) ?? {}
  } catch {
    return {}
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `environments-list-columns-${userId ?? 'guest'}`
  try {
    localStorage.setItem(key, JSON.stringify(model))
  } catch {
    // quota exceeded or storage unavailable — silently skip persistence
  }
}

export default function EnvironmentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { environments, loading, error } = useSelector((state: RootState) => state.environment);
  const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['environment'] ?? []);

  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<EnvironmentStatus | 'all'>('all');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EnvironmentResponse | null>(null);
  const [form, setForm] = useState<EnvFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<EnvironmentResponse | null>(null);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  const user = useSelector((state: RootState) => state.auth.user)
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  )

  useEffect(() => {
    dispatch(fetchEnvironments());
    dispatch(fetchDefinitions('environment'));
  }, [dispatch]);

  const filtered = useMemo(
    () => environments.filter((e) => {
      const matchesSearch = e.name.toLowerCase().includes(search.toLowerCase());
      const matchesStatus = statusFilter === 'all' || e.status === statusFilter;
      return matchesSearch && matchesStatus;
    }),
    [environments, search, statusFilter]
  );

  const openCreate = useCallback(() => {
    setEditTarget(null);
    setForm(emptyForm);
    setCustomFieldValues({});
    setFormError('');
    setDialogOpen(true);
  }, []);

  const openEdit = useCallback((env: EnvironmentResponse) => {
    setEditTarget(env);
    setForm({
      name: env.name,
      description: env.description ?? '',
      environment_type: env.environment_type,
      status: env.status,
    });
    setCustomFieldValues(env.custom_fields ?? {});
    setFormError('');
    setDialogOpen(true);
  }, []);

  const coreColumns = useMemo<GridColDef<EnvironmentResponse>[]>(() => [
    {
      field: 'name',
      headerName: 'Name',
      flex: 1.5,
      hideable: false,
      renderCell: (params) => (
        <Typography variant="body2" fontWeight="medium">{params.row.name}</Typography>
      ),
    },
    {
      field: 'environment_type',
      headerName: 'Type',
      flex: 1,
      hideable: false,
    },
    {
      field: 'status',
      headerName: 'Status',
      flex: 0.8,
      hideable: false,
      renderCell: (params) => (
        <Chip
          label={params.row.status}
          size="small"
          color={STATUS_COLORS[params.row.status]}
        />
      ),
    },
    {
      field: 'created_at',
      headerName: 'Created',
      flex: 0.8,
      hideable: false,
      valueGetter: (params: GridValueGetterParams<EnvironmentResponse>) =>
        new Date(params.row.created_at).toLocaleDateString(),
    },
    {
      field: 'actions',
      headerName: '',
      width: 100,
      sortable: false,
      hideable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <Box onClick={(e) => e.stopPropagation()}>
          <Tooltip title="Edit">
            <IconButton size="small" onClick={() => openEdit(params.row)}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete">
            <IconButton size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      ),
    },
  ], [openEdit, setDeleteTarget])

  const customFieldColumns = useMemo<GridColDef<EnvironmentResponse>[]>(
    () => customFieldDefs.map((def) => ({
      field: def.field_key,
      headerName: def.label,
      flex: 1,
      valueGetter: (params: GridValueGetterParams<EnvironmentResponse>) =>
        params.row.custom_fields?.[def.field_key] ?? '—',
    } as GridColDef<EnvironmentResponse>)),
    [customFieldDefs]
  )

  const columns = useMemo(
    () => [...coreColumns, ...customFieldColumns],
    [coreColumns, customFieldColumns]
  )

  const handleColumnVisibilityChange = useCallback((model: GridColumnVisibilityModel) => {
    setColumnVisibilityModel(model)
    saveColumnModel(user?.id, model)
  }, [user?.id])

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
          custom_fields: customFieldValues,
        };
        await dispatch(updateEnvironment({ id: editTarget.id, data })).unwrap();
      } else {
        const data: EnvironmentCreate = {
          name: form.name,
          description: form.description || undefined,
          environment_type: form.environment_type,
          status: form.status,
          custom_fields: customFieldValues,
        };
        await dispatch(createEnvironment(data)).unwrap();
      }
      setCustomFieldValues({});
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

      <DataGrid
        rows={filtered}
        columns={columns}
        loading={loading && environments.length === 0}
        onRowClick={(params) => navigate(`/environments/${params.row.id}`)}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setCustomFieldValues({}); }} maxWidth="sm" fullWidth>
        <DialogTitle>{editTarget ? 'Edit Environment' : 'New Environment'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '32px' }}>
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
          <CustomFieldsSection
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={setCustomFieldValues}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setDialogOpen(false); setCustomFieldValues({}); }}>Cancel</Button>
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
