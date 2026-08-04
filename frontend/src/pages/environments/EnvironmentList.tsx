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
import { useAllEnvironmentTiers } from '../../hooks/useAllEnvironmentTiers';
import { formatExpiry } from '../../utils/dates';
import api from '../../services/api';

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
  tier_id: number | '';
  owner_user_id: number | '';
  /** "YYYY-MM-DD" from `<input type="date">`, or '' for no expiry planned. */
  expires_at: string;
  status: EnvironmentStatus;
}

const emptyForm: EnvFormValues = {
  name: '',
  description: '',
  tier_id: '',
  owner_user_id: '',
  expires_at: '',
  status: 'active',
};

// Custom-field columns are namespaced under this prefix (see
// buildCustomFieldColumns below) so a tenant-defined field_key can never
// collide with a static column's `field` — see the module-level comment
// there for why that matters.
const CUSTOM_FIELD_COLUMN_PREFIX = 'cf_';

// Read once from the static column list itself (never hardcoded) so this
// stays correct if a static column is ever added, renamed or removed.
const STATIC_COLUMN_FIELDS = () => environmentColumns.map((c) => c.field as string);

// eslint-disable-next-line react-refresh/only-export-components
export function loadColumnModel(
  userId: number | string | undefined,
  knownStaticFields: readonly string[] = STATIC_COLUMN_FIELDS()
): GridColumnVisibilityModel {
  const key = `environments-list-columns-${userId ?? 'guest'}`;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    const parsed = (JSON.parse(raw) ?? {}) as Record<string, boolean>;
    if (typeof parsed !== 'object' || parsed === null) return {};
    const known = new Set(knownStaticFields);
    // A `cf_`-prefixed key always belongs to the custom-field namespace, so
    // it's kept regardless of whether *this* tenant's currently-loaded
    // definitions include it — those load asynchronously (see
    // fetchDefinitions in the component below), and dropping a namespaced
    // entry just because definitions haven't arrived yet on this render
    // would silently discard a real saved preference. A non-namespaced key
    // is kept only if it names a column that still exists today; this is
    // what stops a stale entry surviving indefinitely once its column is
    // gone. Note it does NOT retroactively fix an entry whose key was
    // already reused by a *new* static column of the same name before this
    // fix shipped (see EnvironmentList's commit message) — that key is
    // legitimately "known" either way, so it can't be told apart from a
    // real preference for the new column.
    return Object.fromEntries(
      Object.entries(parsed).filter(
        ([field]) => field.startsWith(CUSTOM_FIELD_COLUMN_PREFIX) || known.has(field)
      )
    );
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
// "environments"): name, tier, status, owner, expires_at, created_at.
// `actions` has no backing column, `reserved_now` is derived from live
// bookings rather than stored (so the backend cannot sort by it), and
// per-tenant custom fields (built separately below, see
// buildCustomFieldColumns) are never in the backend's sort whitelist — none
// of those ever was or can be sortable.
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
    field: 'tier',
    headerName: 'Tier',
    flex: 1,
    hideable: false,
    renderCell: (params) => (
      <Chip
        label={params.row.tier_name}
        size="small"
        sx={{
          bgcolor: params.row.tier_color ?? undefined,
          color: params.row.tier_color ? 'common.white' : undefined,
        }}
      />
    ),
  },
  {
    field: 'owner',
    headerName: 'Owner',
    flex: 1,
    renderCell: (params) => params.row.owner_username ?? '— unowned',
  },
  {
    field: 'expires_at',
    headerName: 'Expires',
    flex: 0.9,
    renderCell: (params) => (
      <Typography
        variant="body2"
        color={
          params.row.expires_at && new Date(params.row.expires_at) < new Date()
            ? 'error.main'
            : 'text.primary'
        }
      >
        {formatExpiry(params.row.expires_at)}
      </Typography>
    ),
  },
  {
    field: 'reserved_now',
    headerName: 'Reserved',
    flex: 0.7,
    // Not in the backend's sort whitelist — it is computed from live bookings,
    // not a stored column. A header that looks clickable and 422s on click is
    // the exact failure test_sort_whitelist_contract exists to prevent.
    sortable: false,
    renderCell: (params) =>
      params.row.reserved_now ? <Chip label="Reserved" size="small" color="info" /> : '—',
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
//
// The grid `field` is namespaced with CUSTOM_FIELD_COLUMN_PREFIX rather than
// using `def.field_key` directly: field_key is tenant-chosen and free-text
// (e.g. a demo tenant defined one keyed 'owner', to record an owner before
// this page had a real Owner column), so an unnamespaced field can collide
// with a static column's `field` of the same name — and did. MUI then treats
// both grid entries as the same column internally (same `field` = same
// lookup key), which duplicates the rendered header AND, worse, means a
// visibility toggle persisted for one silently hides the other too. The
// prefix is grid-internal only: `headerName` still reads `def.label`, and
// the value is still looked up by the raw `def.field_key` inside
// `custom_fields`, so nothing user-visible changes.
// eslint-disable-next-line react-refresh/only-export-components
export function buildCustomFieldColumns(
  defs: CustomFieldDefinition[]
): GridColDef<EnvironmentResponse>[] {
  return defs.map(
    (def) =>
      ({
        field: `${CUSTOM_FIELD_COLUMN_PREFIX}${def.field_key}`,
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

  // Never `state.environment.environments`: that is one server-paged window,
  // so a picker reading it would silently offer whatever tiers happened to be
  // on the visible page.
  const { tiers } = useAllEnvironmentTiers();

  // GET /tenant/users/lite is knowingly unbounded — one of the five
  // growth-bearing endpoints docs/pagination.md lists as not yet bounded.
  // Adding a consumer here is deliberate; bounding it is that item's job.
  // (GatesTable.tsx calls it the same way.)
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    api
      .get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([])); // owner select stays empty on failure
  }, []);

  const grid = useServerGrid({
    endpoint: 'environments',
    filterKeys: ['search', 'status', 'tier_id', 'governance_gap'],
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
      tier_id: env.tier_id,
      owner_user_id: env.owner_user_id ?? '',
      expires_at: env.expires_at ? env.expires_at.slice(0, 10) : '',
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
    if (!form.tier_id) {
      setFormError('Tier is required');
      return;
    }
    if (!form.owner_user_id) {
      setFormError('A named owner is required');
      return;
    }
    // Expiry is required on create only. A null expiry means "no expiry
    // planned" — a legitimate state the backend deliberately exempts from its
    // compliance rule — so demanding one here would make every
    // spreadsheet-imported environment uneditable in the UI.
    if (!editTarget && !form.expires_at) {
      setFormError('An expiry date is required');
      return;
    }
    try {
      if (editTarget) {
        const data: EnvironmentUpdate = {
          name: form.name,
          description: form.description || undefined,
          tier_id: Number(form.tier_id),
          owner_user_id: Number(form.owner_user_id),
          // Explicit null, not undefined: blanking the field clears the
          // expiry rather than silently leaving the stored one in place.
          expires_at: form.expires_at
            ? new Date(`${form.expires_at}T00:00:00Z`).toISOString()
            : null,
          status: form.status,
          custom_fields: customFieldValues,
        };
        await dispatch(updateEnvironment({ id: editTarget.id, data })).unwrap();
      } else {
        const data: EnvironmentCreate = {
          name: form.name,
          description: form.description || undefined,
          tier_id: Number(form.tier_id),
          owner_user_id: Number(form.owner_user_id),
          expires_at: new Date(`${form.expires_at}T00:00:00Z`).toISOString(),
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

      {/* Status / tier / governance filters */}
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
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
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel id="tier-filter-label">Tier</InputLabel>
          <Select
            labelId="tier-filter-label"
            label="Tier"
            value={grid.filters.tier_id ?? ''}
            onChange={(e) => grid.setFilter('tier_id', e.target.value)}
          >
            {/* '' is the no-selection value, NOT 'all': buildParams drops ''
                and also drops the literal 'all' for non-text keys, so a
                vocabulary containing 'all' would build params byte-identical
                to "no selection" and the grid would never refetch. */}
            <MenuItem value="">Any tier</MenuItem>
            {tiers
              .filter((t) => t.is_active)
              .map((t) => (
                <MenuItem key={t.id} value={String(t.id)}>
                  {t.name}
                </MenuItem>
              ))}
          </Select>
        </FormControl>
        <Chip
          // `governance_gap` is a missing OWNER only — a null expiry means "no
          // expiry planned", a legitimate state rather than a gap.
          label="Missing owner"
          clickable
          color={grid.filters.governance_gap === 'true' ? 'warning' : 'default'}
          variant={grid.filters.governance_gap === 'true' ? 'filled' : 'outlined'}
          onClick={() =>
            grid.setFilter('governance_gap', grid.filters.governance_gap === 'true' ? '' : 'true')
          }
        />
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
          <FormControl fullWidth required>
            <InputLabel id="env-form-tier-label">Tier</InputLabel>
            <Select
              labelId="env-form-tier-label"
              label="Tier"
              value={form.tier_id}
              onChange={(e) => setForm({ ...form, tier_id: Number(e.target.value) })}
            >
              {/* An inactive tier stays selectable only when it is the one
                  already on this environment, so editing an environment on a
                  retired tier does not silently change its tier. */}
              {tiers
                .filter((t) => t.is_active || t.id === form.tier_id)
                .map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.name}
                  </MenuItem>
                ))}
            </Select>
          </FormControl>
          <FormControl fullWidth required>
            <InputLabel id="env-form-owner-label">Owner</InputLabel>
            <Select
              labelId="env-form-owner-label"
              label="Owner"
              value={form.owner_user_id}
              onChange={(e) => setForm({ ...form, owner_user_id: Number(e.target.value) })}
            >
              {/* GET /tenant/users/lite filters to active users, but the
                  backend's owner validation does not check is_active, so an
                  environment can legitimately hold a deactivated owner. Keep
                  that owner selectable (labelled as inactive) the same way
                  the tier Select above keeps a retired tier selectable —
                  otherwise the required field renders blank with a MUI
                  out-of-range warning while form state still holds the id.
                  `editTarget.owner_username` supplies the label since the
                  lite list won't have this user at all. */}
              {editTarget &&
                form.owner_user_id === editTarget.owner_user_id &&
                !users.some((u) => u.id === form.owner_user_id) && (
                  <MenuItem value={form.owner_user_id}>
                    {editTarget.owner_username ?? `#${form.owner_user_id}`} (inactive)
                  </MenuItem>
                )}
              {users.map((u) => (
                <MenuItem key={u.id} value={u.id}>
                  {u.username}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            label="Expires"
            type="date"
            // Required on create only — see handleSave. Blank on edit means
            // "no expiry planned", not an unfinished form.
            required={!editTarget}
            helperText={editTarget ? 'Leave blank for no expiry planned' : undefined}
            value={form.expires_at}
            onChange={(e) => setForm({ ...form, expires_at: e.target.value })}
            InputLabelProps={{ shrink: true }}
            fullWidth
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
