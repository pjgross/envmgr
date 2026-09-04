import { useCallback, useMemo, useState } from 'react';
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
  FormControl,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Select,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import { DataGrid, GridColDef, GridRenderCellParams, GridValueGetterParams } from '@mui/x-data-grid';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';

import type { AppDispatch, RootState } from '../../store';
import {
  createInfrastructureComponent,
  deleteInfrastructureComponent,
  fetchInfrastructureComponents,
  updateInfrastructureComponent,
} from '../../store/infrastructureComponentSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import {
  COMPONENT_TYPE_OPTIONS,
  SOURCE_OPTIONS,
  type InfrastructureComponentCreate,
  type InfrastructureComponentResponse,
  type InfrastructureComponentSource,
  type InfrastructureComponentType,
  type InfrastructureComponentUpdate,
} from '../../types/infrastructureComponent';
import PageHeader from '../../components/layout/PageHeader';

interface FormValues {
  name: string;
  description: string;
  component_type: InfrastructureComponentType;
  provider: string;
  region: string;
  location: string;
  source: InfrastructureComponentSource;
  external_id: string;
}

const emptyForm: FormValues = {
  name: '',
  description: '',
  component_type: 'server',
  provider: '',
  region: '',
  location: '',
  source: 'manual',
  external_id: '',
};

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "infrastructure-components"): name, component_type, provider, region,
// source. `location` is a real, visible data column — unlike every other
// unsortable column on this page's siblings (computed or joined), this one
// looks like an ordinary column and is NOT in the backend's whitelist; a
// sortable header on it 422s on first click. `actions` has no backing
// column either. Both flags are written out literally below, never derived
// from `isSortable`, so this array can't become a tautology of itself.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file). The
// `actions` column's renderCell is filled in at render time (see `columns`
// below) because it needs to close over this component's own dialog/state
// handlers; everything else here is exactly what's rendered.
// eslint-disable-next-line react-refresh/only-export-components
export const infraComponentColumns: GridColDef<InfrastructureComponentResponse>[] = [
  {
    field: 'name',
    headerName: 'Name',
    flex: 1.5,
    renderCell: (params) => (
      <Typography variant="body2" fontWeight="medium">
        {params.row.name}
      </Typography>
    ),
  },
  {
    field: 'component_type',
    headerName: 'Type',
    flex: 1.2,
    valueGetter: (params: GridValueGetterParams<InfrastructureComponentResponse>) =>
      COMPONENT_TYPE_OPTIONS.find((o) => o.value === params.row.component_type)?.label ??
      params.row.component_type,
  },
  { field: 'provider', headerName: 'Provider', flex: 1 },
  { field: 'region', headerName: 'Region', flex: 1 },
  { field: 'location', headerName: 'Location', flex: 1, sortable: false },
  {
    field: 'source',
    headerName: 'Source',
    flex: 0.8,
    renderCell: (params) => (
      <Chip
        size="small"
        label={params.row.source}
        color={params.row.source === 'manual' ? 'default' : 'info'}
      />
    ),
  },
  {
    field: 'actions',
    headerName: '',
    width: 100,
    sortable: false,
    disableColumnMenu: true,
  },
];

export default function InfrastructureComponentList() {
  const dispatch = useDispatch<AppDispatch>();
  const { components, total, loading, listLoading, error } = useSelector(
    (state: RootState) => state.infrastructureComponent
  );

  const grid = useServerGrid({
    endpoint: 'infrastructure-components',
    filterKeys: ['search', 'component_type'],
    // Free-text keys, and also the 'all'-sentinel exemption list. Every entry
    // must also appear in filterKeys above — there is a DEV warning if not.
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchInfrastructureComponents(params)),
    total,
    totalPending: listLoading,
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<InfrastructureComponentResponse | null>(null);
  const [form, setForm] = useState<FormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<InfrastructureComponentResponse | null>(null);
  const [deleteError, setDeleteError] = useState('');

  const openCreate = useCallback(() => {
    setEditTarget(null);
    setForm(emptyForm);
    setFormError('');
    setDialogOpen(true);
  }, []);

  const openEdit = useCallback((row: InfrastructureComponentResponse) => {
    setEditTarget(row);
    setForm({
      name: row.name,
      description: row.description ?? '',
      component_type: row.component_type,
      provider: row.provider ?? '',
      region: row.region ?? '',
      location: row.location ?? '',
      source: row.source,
      external_id: row.external_id ?? '',
    });
    setFormError('');
    setDialogOpen(true);
  }, []);

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Name is required');
      return;
    }
    try {
      if (editTarget) {
        const data: InfrastructureComponentUpdate = {
          name: form.name,
          description: form.description || undefined,
          component_type: form.component_type,
          provider: form.provider || undefined,
          region: form.region || undefined,
          location: form.location || undefined,
          source: form.source,
          external_id: form.external_id || undefined,
        };
        await dispatch(updateInfrastructureComponent({ id: editTarget.id, data })).unwrap();
      } else {
        const data: InfrastructureComponentCreate = {
          name: form.name,
          description: form.description || undefined,
          component_type: form.component_type,
          provider: form.provider || undefined,
          region: form.region || undefined,
          location: form.location || undefined,
          source: form.source,
          external_id: form.external_id || undefined,
        };
        await dispatch(createInfrastructureComponent(data)).unwrap();
      }
      // Re-issue the current page/sort/filter query — the slice no longer
      // splices the created/updated row into its list, since that list is
      // now one server-paged window, not the whole result set.
      grid.refetch();
      setDialogOpen(false);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setFormError(message || 'Failed to save host');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    setDeleteError('');
    try {
      await dispatch(deleteInfrastructureComponent(deleteTarget.id)).unwrap();
      // Same reason as handleSave above — not a bare
      // dispatch(fetchInfrastructureComponents()), which would clobber the
      // current page/sort/filter with the endpoint's unfiltered page-1
      // default.
      grid.refetch();
      setDeleteTarget(null);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setDeleteError(message || 'Failed to delete host');
    }
  };

  // infraComponentColumns ends with the literal `actions` GridColDef (no
  // renderCell — see its JSDoc above); its renderCell is filled in here
  // because it needs to close over this component's own dialog/state
  // handlers.
  const columns = useMemo<GridColDef<InfrastructureComponentResponse>[]>(() => {
    const staticCols = infraComponentColumns.filter((col) => col.field !== 'actions');
    const actionsCol: GridColDef<InfrastructureComponentResponse> = {
      ...(infraComponentColumns.find(
        (col) => col.field === 'actions'
      ) as GridColDef<InfrastructureComponentResponse>),
      renderCell: (params: GridRenderCellParams<InfrastructureComponentResponse>) => (
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
    return [...staticCols, actionsCol];
  }, [openEdit]);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Hosts & infrastructure"
        actions={
          <>
            <TextField
              size="small"
              placeholder="Search hosts…"
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
            <FormControl size="small" sx={{ minWidth: 180 }}>
              <InputLabel>Type</InputLabel>
              <Select
                label="Type"
                value={grid.filters.component_type ?? 'all'}
                onChange={(e) => grid.setFilter('component_type', e.target.value)}
              >
                <MenuItem value="all">All types</MenuItem>
                {COMPONENT_TYPE_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
              New Host
            </Button>
          </>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <DataGrid
        rows={components}
        columns={columns}
        loading={listLoading && components.length === 0}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        // `rows` is one windowed page, not the whole result set. MUI's
        // column-menu "Filter" item is gated only on this prop / a column's
        // own `filterable` — not on whether a toolbar is rendered — so
        // without it every header's menu offers a filter that would
        // silently filter the loaded page while the footer keeps showing
        // the true server `rowCount`.
        disableColumnFilter
        paginationModel={grid.paginationModel}
        onPaginationModelChange={grid.onPaginationModelChange}
        sortModel={grid.sortModel}
        onSortModelChange={grid.onSortModelChange}
        pageSizeOptions={[10, 25, 50, 100]}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      <Dialog open={dialogOpen} onClose={() => setDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{editTarget ? 'Edit Host' : 'New Host'}</DialogTitle>
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
          <FormControl fullWidth>
            <InputLabel>Type</InputLabel>
            <Select
              label="Type"
              value={form.component_type}
              onChange={(e) =>
                setForm({
                  ...form,
                  component_type: e.target.value as InfrastructureComponentType,
                })
              }
            >
              {COMPONENT_TYPE_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Box sx={{ display: 'flex', gap: 2 }}>
            <TextField
              label="Provider"
              value={form.provider}
              onChange={(e) => setForm({ ...form, provider: e.target.value })}
              fullWidth
              placeholder="aws, gcp, orbstack, on_premise…"
            />
            <TextField
              label="Region"
              value={form.region}
              onChange={(e) => setForm({ ...form, region: e.target.value })}
              fullWidth
              placeholder="e.g. eu-west-1"
            />
          </Box>
          <TextField
            label="Location"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            fullWidth
            placeholder="Physical hint, e.g. macmini.lan"
          />
          <Box sx={{ display: 'flex', gap: 2 }}>
            <FormControl fullWidth>
              <InputLabel>Source</InputLabel>
              <Select
                label="Source"
                value={form.source}
                onChange={(e) =>
                  setForm({
                    ...form,
                    source: e.target.value as InfrastructureComponentSource,
                  })
                }
              >
                {SOURCE_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>
                    {o.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="External ID"
              value={form.external_id}
              onChange={(e) => setForm({ ...form, external_id: e.target.value })}
              fullWidth
              placeholder="For future IaC matching"
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleSave} variant="contained" disabled={loading}>
            {editTarget ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(deleteTarget)}
        onClose={() => {
          setDeleteTarget(null);
          setDeleteError('');
        }}
      >
        <DialogTitle>Delete Host</DialogTitle>
        <DialogContent>
          {deleteError && <Alert severity="error" sx={{ mb: 2 }}>{deleteError}</Alert>}
          <Typography>
            Are you sure you want to delete <strong>{deleteTarget?.name}</strong>?
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDeleteTarget(null);
              setDeleteError('');
            }}
          >
            Cancel
          </Button>
          <Button onClick={handleDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
