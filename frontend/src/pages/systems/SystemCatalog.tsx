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
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  GridColDef,
  GridRenderCellParams,
  GridValueGetterParams,
} from '@mui/x-data-grid';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';
import LinkIcon from '@mui/icons-material/Link';

import DataTable from '../../components/DataTable';
import type { AppDispatch, RootState } from '../../store';
import { fetchSystems, createSystem, updateSystem, deleteSystem } from '../../store/systemSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { SystemResponse, SystemCreate, SystemUpdate } from '../../types/system';
import type { CustomFieldDefinition } from '../../types/customField';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import { useSnackbar } from '../../hooks/useSnackbar';
import PageHeader from '../../components/layout/PageHeader';

interface SystemFormValues {
  name: string;
  description: string;
  github_repository_url: string;
}

const emptyForm: SystemFormValues = { name: '', description: '', github_repository_url: '' };

// Custom-field columns are namespaced under this prefix (see
// buildCustomFieldColumns below) so a tenant-defined field_key can never
// collide with a static column's `field` — see the module-level comment
// there for why that matters.
const CUSTOM_FIELD_COLUMN_PREFIX = 'cf_';

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "systems"): `name` ALONE. `description` and `github_repository_url` are
// ordinary, visible data columns — unlike every other unsortable column on
// this page's siblings (computed or joined), these look like ordinary
// columns and are NOT in the backend's whitelist; a sortable header on
// either 422s on first click. `actions` has no backing column either. All
// three flags are written out literally below, never derived from
// `isSortable`, so this array can't become a tautology of itself.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file). The
// `actions` column's renderCell is filled in at render time (see `columns`
// below) because it needs to close over this component's own dialog/state
// handlers; everything else here is exactly what's rendered.
// eslint-disable-next-line react-refresh/only-export-components
export const systemColumns: GridColDef<SystemResponse>[] = [
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
    field: 'description',
    headerName: 'Description',
    flex: 2,
    hideable: false,
    sortable: false,
    valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
      params.row.description ?? '—',
  },
  {
    field: 'github_repository_url',
    headerName: 'GitHub',
    flex: 1,
    hideable: false,
    sortable: false,
    renderCell: (params) =>
      params.row.github_repository_url ? (
        <Chip
          icon={<LinkIcon />}
          label="GitHub"
          size="small"
          component="a"
          href={params.row.github_repository_url}
          target="_blank"
          rel="noopener noreferrer"
          clickable
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <Typography variant="body2" color="text.secondary">
          —
        </Typography>
      ),
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
// which fields the tenant has defined), unlike the static `systemColumns`
// above — pulled out to a plain function so the `sortable: false` on them is
// unit-testable the same way, since none of these fields is ever in the
// backend's sort whitelist (they're tenant-defined, not schema columns).
//
// The `field` is namespaced `cf_<key>`, never the raw `field_key`. A tenant is
// free to key a custom field `description` — an entirely ordinary thing to do —
// and without the prefix that GridColDef would share its `field` with the
// static Description column. MUI keys its column lookup by `field`, so two
// entries sharing one become a single column: duplicate headers, and toggling
// visibility on one silently hides the other, which DataTable's own
// persistence then saves across reloads. EnvironmentList shipped exactly
// this bug when a static `owner` column met the demo tenant's `owner`
// custom field.
//
// The prefix is a grid-column id only: `custom_fields` on the row is still
// keyed by the tenant's own `field_key`, so the valueGetter reads the raw key.
// eslint-disable-next-line react-refresh/only-export-components
export function buildCustomFieldColumns(
  defs: CustomFieldDefinition[]
): GridColDef<SystemResponse>[] {
  return defs.map(
    (def) =>
      ({
        field: `${CUSTOM_FIELD_COLUMN_PREFIX}${def.field_key}`,
        headerName: def.label,
        flex: 1,
        sortable: false,
        valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
          params.row.custom_fields?.[def.field_key] ?? '—',
      }) as GridColDef<SystemResponse>
  );
}

export default function SystemCatalog() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const navigate = useNavigate();
  const { systems, total, loading, listLoading, error } = useSelector(
    (state: RootState) => state.system
  );

  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['system'] ?? []
  );

  const grid = useServerGrid({
    endpoint: 'systems',
    filterKeys: ['search'],
    // Free-text keys, and also the 'all'-sentinel exemption list. Every entry
    // must also appear in filterKeys above — there is a DEV warning if not.
    debounceKeys: ['search'],
    onFetch: (params) => dispatch(fetchSystems(params)),
    total,
    totalPending: listLoading,
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SystemResponse | null>(null);
  const [form, setForm] = useState<SystemFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SystemResponse | null>(null);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  const user = useSelector((state: RootState) => state.auth.user);

  useEffect(() => {
    dispatch(fetchDefinitions('system'));
  }, [dispatch]);

  const openCreate = useCallback(() => {
    setEditTarget(null);
    setForm(emptyForm);
    setFormError('');
    setCustomFieldValues({});
    setDialogOpen(true);
  }, []);

  const openEdit = useCallback((system: SystemResponse) => {
    setEditTarget(system);
    setForm({
      name: system.name,
      description: system.description ?? '',
      github_repository_url: system.github_repository_url ?? '',
    });
    setFormError('');
    setCustomFieldValues(system.custom_fields ?? {});
    setDialogOpen(true);
  }, []);

  // systemColumns ends with the literal `actions` GridColDef (no renderCell —
  // see its JSDoc above); the per-tenant custom-field columns go between the
  // static columns and it, matching this page's pre-conversion layout
  // (custom fields before the action buttons).
  const columns = useMemo<GridColDef<SystemResponse>[]>(() => {
    const staticCols = systemColumns.filter((col) => col.field !== 'actions');
    const actionsCol: GridColDef<SystemResponse> = {
      ...(systemColumns.find((col) => col.field === 'actions') as GridColDef<SystemResponse>),
      renderCell: (params: GridRenderCellParams<SystemResponse>) => (
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

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Name is required');
      return;
    }
    try {
      if (editTarget) {
        const data: SystemUpdate = {
          name: form.name,
          description: form.description || undefined,
          github_repository_url: form.github_repository_url || undefined,
          custom_fields: customFieldValues,
        };
        await dispatch(updateSystem({ id: editTarget.id, data })).unwrap();
      } else {
        const data: SystemCreate = {
          name: form.name,
          description: form.description || undefined,
          github_repository_url: form.github_repository_url || undefined,
          custom_fields: customFieldValues,
        };
        await dispatch(createSystem(data)).unwrap();
      }
      // Re-issue the current page/sort/filter query — the slice no longer
      // splices the created/updated row into its list, since that list is
      // now one server-paged window, not the whole result set.
      grid.refetch();
      setDialogOpen(false);
      setCustomFieldValues({});
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setFormError(message || 'Failed to save system');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await dispatch(deleteSystem(deleteTarget.id)).unwrap();
      // Same reason as handleSave above — not a bare dispatch(fetchSystems()),
      // which would clobber the current page/sort/filter with the endpoint's
      // unfiltered page-1 default.
      grid.refetch();
      snackbar.success('System deleted');
      setDeleteTarget(null);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete system');
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="System catalog"
        actions={
          <>
            <TextField
              size="small"
              placeholder="Search systems…"
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
              New System
            </Button>
          </>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <DataTable
        storageKey="systems-list-columns"
        userId={user?.id ?? 'guest'}
        emptyMessage="No systems match these filters."
        rows={systems}
        columns={columns}
        loading={listLoading && systems.length === 0}
        onRowClick={(params) => navigate(`/systems/${params.row.id}`)}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        // `rows` is one windowed page, not the whole result set. MUI's
        // column-menu "Filter" item is gated only on this prop / a column's
        // own `filterable` — not on whether a toolbar is rendered — so
        // without it every header's menu offers a filter that would
        // silently filter the loaded page while the footer keeps showing
        // the true server `rowCount`. DataTable defaults this on in server
        // mode; kept explicit because `{...rest}` lets a caller override it.
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
        <DialogTitle>{editTarget ? 'Edit System' : 'New System'}</DialogTitle>
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
            label="GitHub Repository URL"
            value={form.github_repository_url}
            onChange={(e) => setForm({ ...form, github_repository_url: e.target.value })}
            fullWidth
            placeholder="https://github.com/org/repo"
          />
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
        <DialogTitle>Delete System</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{deleteTarget?.name}</strong>? This will also
            delete all its subsystems.
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
