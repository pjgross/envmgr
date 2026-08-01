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
  GridRenderCellParams,
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
import { useServerGrid } from '../../hooks/useServerGrid';
import type {
  EnvironmentResponse,
  EnvironmentStatus,
  EnvironmentCreate,
  EnvironmentUpdate,
} from '../../types/environment';
import type { CustomFieldDefinition } from '../../types/customField';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import { useSnackbar } from '../../hooks/useSnackbar';

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
  const key = `environments-list-columns-${userId ?? 'guest'}`;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    return JSON.parse(raw) ?? {};
  } catch {
    return {};
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `environments-list-columns-${userId ?? 'guest'}`;
  try {
    localStorage.setItem(key, JSON.stringify(model));
  } catch {
    // quota exceeded or storage unavailable — silently skip persistence
  }
}

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "environments"): name, environment_type, status, created_at. `actions` has no
// backing column, and per-tenant custom fields (built separately below, see
// buildCustomFieldColumns) are never in the backend's sort whitelist — neither
// ever was or can be sortable.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file). The
// `actions` column's renderCell is filled in at render time (see `columns`
// below) because it needs to close over this component's own dialog/state
// handlers; everything else here is exactly what's rendered.
// eslint-disable-next-line react-refresh/only-export-components
export const environmentColumns: GridColDef<EnvironmentResponse>[] = [
  {
    field: 'name',
    headerName: 'Name',
    flex: 1.5,
    hideable: false,
    renderCell: (params) => (
      <Typography variant="body2" fontWeight="medium">
        {params.row.name}
      </Typography>
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
      <Chip label={params.row.status} size="small" color={STATUS_COLORS[params.row.status]} />
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
  },
];

// Per-tenant custom-field columns are built at render time (they depend on
// which fields the tenant has defined), unlike the static `environmentColumns`
// above — pulled out to a plain function so the `sortable: false` on them is
// unit-testable the same way, since none of these fields is ever in the
// backend's sort whitelist (they're tenant-defined, not schema columns).
// eslint-disable-next-line react-refresh/only-export-components
export function buildCustomFieldColumns(
  defs: CustomFieldDefinition[]
): GridColDef<EnvironmentResponse>[] {
  return defs.map(
    (def) =>
      ({
        field: def.field_key,
        headerName: def.label,
        flex: 1,
        sortable: false,
        valueGetter: (params: GridValueGetterParams<EnvironmentResponse>) =>
          params.row.custom_fields?.[def.field_key] ?? '—',
      }) as GridColDef<EnvironmentResponse>
  );
}

export default function EnvironmentList() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const navigate = useNavigate();
  const { environments, total, loading, listLoading, error } = useSelector(
    (state: RootState) => state.environment
  );
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['environment'] ?? []
  );

  const grid = useServerGrid({
    endpoint: 'environments',
    filterKeys: ['search', 'status', 'environment_type'],
    // Free-text keys, and also the 'all'-sentinel exemption list. Every entry
    // must also appear in filterKeys above — there is a DEV warning if not.
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchEnvironments(params)),
    total,
    totalPending: listLoading,
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<EnvironmentResponse | null>(null);
  const [form, setForm] = useState<EnvFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<EnvironmentResponse | null>(null);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  const user = useSelector((state: RootState) => state.auth.user);
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  );

  useEffect(() => {
    dispatch(fetchDefinitions('environment'));
  }, [dispatch]);

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

  // environmentColumns ends with the literal `actions` GridColDef (no
  // renderCell — see its JSDoc above); the per-tenant custom-field columns go
  // between the static columns and it, matching this page's pre-conversion
  // layout (custom fields before the action buttons).
  const columns = useMemo<GridColDef<EnvironmentResponse>[]>(() => {
    const staticCols = environmentColumns.filter((col) => col.field !== 'actions');
    const actionsCol: GridColDef<EnvironmentResponse> = {
      ...(environmentColumns.find((col) => col.field === 'actions') as GridColDef<EnvironmentResponse>),
      renderCell: (params: GridRenderCellParams<EnvironmentResponse>) => (
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
    };
    return [...staticCols, ...buildCustomFieldColumns(customFieldDefs), actionsCol];
  }, [customFieldDefs, openEdit]);

  const handleColumnVisibilityChange = useCallback(
    (model: GridColumnVisibilityModel) => {
      setColumnVisibilityModel(model);
      saveColumnModel(user?.id, model);
    },
    [user?.id]
  );

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
      // Re-issue the current page/sort/filter query — the slice no longer
      // splices the created/updated row into its list, since that list is
      // now one server-paged window, not the whole result set.
      grid.refetch();
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
      // Same reason as handleSave above — not a bare dispatch(fetchEnvironments()),
      // which would clobber the current page/sort/filter with the endpoint's
      // unfiltered page-1 default.
      grid.refetch();
      snackbar.success('Environment deleted');
      setDeleteTarget(null);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete environment');
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
          value={grid.filters.search ?? ''}
          onChange={(e) => grid.setFilter('search', e.target.value)}
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
            color={(grid.filters.status ?? 'all') === f.value ? 'primary' : 'default'}
            variant={(grid.filters.status ?? 'all') === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('status', f.value)}
          />
        ))}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <DataGrid
        rows={environments}
        columns={columns}
        loading={listLoading && environments.length === 0}
        onRowClick={(params) => navigate(`/environments/${params.row.id}`)}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        // `rows` is one windowed page, not the whole result set. MUI's
        // column-menu "Filter" item is gated only on this prop / a column's
        // own `filterable` — not on whether a toolbar is rendered — so
        // without it every header's menu offers a filter that would
        // silently filter the loaded page while the footer keeps showing
        // the true server `rowCount`. See DataTable.tsx's server-mode
        // default for the same guard.
        disableColumnFilter
        paginationModel={grid.paginationModel}
        onPaginationModelChange={grid.onPaginationModelChange}
        sortModel={grid.sortModel}
        onSortModelChange={grid.onSortModelChange}
        pageSizeOptions={[10, 25, 50, 100]}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* Create / Edit Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => {
          setDialogOpen(false);
          setCustomFieldValues({});
        }}
        maxWidth="sm"
        fullWidth
      >
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
          <CustomFieldsSection
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={setCustomFieldValues}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDialogOpen(false);
              setCustomFieldValues({});
            }}
          >
            Cancel
          </Button>
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
