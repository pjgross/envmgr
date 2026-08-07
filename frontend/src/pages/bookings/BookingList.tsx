import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  IconButton,
  Menu,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridRenderCellParams,
  GridValueGetterParams,
} from '@mui/x-data-grid';
import { format } from 'date-fns';
import { AppDispatch, RootState } from '../../store';
import { fetchBookings } from '../../store/bookingSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { useAllProjects } from '../../hooks/useAllProjects';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { BookingResponse, BookingStatus } from '../../types/booking';
import type { CustomFieldDefinition } from '../../types/customField';
import type { AllowedTransition } from '../../types/bookingLifecycle';
import { bookingService } from '../../services/bookingService';
import ComputedColumnHeader from '../../components/ComputedColumnHeader';
import ConflictIndicator from '../../components/bookings/ConflictIndicator';
import { formatApiError } from '../../services/apiError';
import BookingForm from './BookingForm';

// --- Status filter -----------------------------------------------------------

const STATUS_OPTIONS: Array<{ label: string; value: BookingStatus | 'all' }> = [
  { label: 'All', value: 'all' },
  { label: 'Draft', value: 'draft' },
  { label: 'Submitted', value: 'submitted' },
  { label: 'Approved', value: 'approved' },
  { label: 'Rejected', value: 'rejected' },
  { label: 'Ext. Requested', value: 'extension_requested' },
  { label: 'Closed', value: 'closed' },
];

const STATUS_COLORS: Record<string, 'default' | 'warning' | 'success' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  extension_requested: 'warning',
  closed: 'info',
};

// --- Column visibility localStorage ------------------------------------------

// Custom-field columns are namespaced under this prefix (see
// buildCustomFieldColumns below) so a tenant-defined field_key can never
// collide with a static column's `field` — see the module-level comment
// there for why that matters.
const CUSTOM_FIELD_COLUMN_PREFIX = 'cf_';

function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `bookings-list-columns-${userId ?? 'guest'}`;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    return JSON.parse(raw) ?? {};
  } catch {
    return {};
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `bookings-list-columns-${userId ?? 'guest'}`;
  localStorage.setItem(key, JSON.stringify(model));
}

// --- Project filter -----------------------------------------------------------

/**
 * The URL spells "no project filter" as `any`, never `all`. `all` is
 * `buildParams`' own "no selection" sentinel and would be dropped before a
 * request is ever built — see ReleaseList's identical `apiProjectId` for the
 * shape of the bug this avoids: two states of a toggle collapsing to
 * byte-identical params so the grid never refetches.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function apiProjectId(urlValue: string | number | undefined): number | undefined {
  if (urlValue === undefined || urlValue === 'any') return undefined;
  const n = Number(urlValue);
  return Number.isFinite(n) ? n : undefined;
}

// --- Columns -------------------------------------------------------------

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "bookings"): start_date, end_date, status. The other columns are joined
// (project_name, project_name_link, environment_name, booked_by_username), a
// per-tenant lookup rendered as a chip (booking_type_id), a per-row kebab
// menu with no backing column (actions), or computed after the page is
// fetched (conflicts) — none is backed by a single column the database could
// order by, so none ever was or can be sortable.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file). The
// `actions` column's renderCell is filled in at render time (see `columns`
// below) because it needs to close over this component's shared kebab-menu
// state; everything else here is exactly what's rendered.
// eslint-disable-next-line react-refresh/only-export-components
export const bookingColumns: GridColDef<BookingResponse>[] = [
  {
    field: 'project_name',
    headerName: 'Purpose',
    flex: 1.5,
    hideable: false,
    sortable: false,
    renderCell: ({ row }) => (
      <Button
        variant="text"
        size="small"
        component={RouterLink}
        to={`/bookings/${row.id}`}
        sx={{ textTransform: 'none', p: 0, minWidth: 0, justifyContent: 'flex-start' }}
      >
        {row.project_name}
      </Button>
    ),
  },
  {
    // Joined — resolved by a batched project_service.get_project_names
    // lookup after the query, never a column the database could order by.
    // Renders project_name_link, never project_id or project_name (the
    // free-text "Purpose" field above, rendered by a different column).
    field: 'project_name_link',
    headerName: 'Project',
    flex: 1,
    sortable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      params.row.project_name_link ?? '—',
  },
  {
    field: 'environment_name',
    headerName: 'Environment',
    flex: 1,
    hideable: false,
    sortable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      params.row.environment_name ?? '—',
  },
  {
    field: 'booked_by_username',
    headerName: 'Booked By',
    flex: 1,
    hideable: false,
    sortable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      params.row.booked_by_username ?? '—',
  },
  {
    field: 'start_date',
    headerName: 'Start',
    flex: 0.8,
    hideable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      format(new Date(params.row.start_date), 'dd MMM yyyy'),
  },
  {
    field: 'end_date',
    headerName: 'End',
    flex: 0.8,
    hideable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      format(new Date(params.row.end_date), 'dd MMM yyyy'),
  },
  {
    field: 'booking_type_id',
    headerName: 'Type',
    flex: 0.8,
    hideable: false,
    sortable: false,
    renderCell: ({ row }) => (
      <Chip label={row.booking_type_id} size="small" color="primary" variant="outlined" />
    ),
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 0.8,
    hideable: false,
    renderCell: ({ row }) => (
      <Chip label={row.status} size="small" color={STATUS_COLORS[row.status]} />
    ),
  },
  {
    field: 'conflicts',
    headerName: 'Conflicts',
    width: 90,
    hideable: false,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Conflicts" />,
    renderCell: ({ row }) => (
      <ConflictIndicator hasUnacknowledged={row.has_unacknowledged_conflicts} />
    ),
  },
  {
    field: 'actions',
    headerName: '',
    width: 48,
    hideable: false,
    sortable: false,
    disableColumnMenu: true,
  },
];

// Per-tenant custom-field columns are built at render time (they depend on
// which fields the tenant has defined), unlike the static `bookingColumns`
// above — pulled out to a plain function so the `sortable: false` on them is
// unit-testable the same way, since none of these fields is ever in the
// backend's sort whitelist (they're tenant-defined, not schema columns).
//
// The `field` is namespaced `cf_<key>`, never the raw `field_key`. A tenant is
// free to key a custom field `project_name` or `status` — entirely ordinary
// things to do — and without the prefix that GridColDef would share its
// `field` with the static column of the same name. MUI keys its column lookup
// by `field`, so two entries sharing one become a single column: duplicate
// headers, and toggling visibility on one silently hides the other, which
// `saveColumnModel` above then persists across reloads. EnvironmentList
// shipped exactly this bug when a static `owner` column met the demo tenant's
// `owner` custom field.
//
// The prefix is a grid-column id only: `custom_fields` on the row is still
// keyed by the tenant's own `field_key`, so the valueGetter reads the raw key.
// eslint-disable-next-line react-refresh/only-export-components
export function buildCustomFieldColumns(
  defs: CustomFieldDefinition[]
): GridColDef<BookingResponse>[] {
  return defs.map(
    (def) =>
      ({
        field: `${CUSTOM_FIELD_COLUMN_PREFIX}${def.field_key}`,
        headerName: def.label,
        flex: 1,
        sortable: false,
        valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
          params.row.custom_fields?.[def.field_key] ?? '—',
      }) as GridColDef<BookingResponse>
  );
}

// --- Component ---------------------------------------------------------------

export default function BookingList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { bookings, total, listLoading, error } = useSelector((state: RootState) => state.booking);
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );
  const user = useSelector((state: RootState) => state.auth.user);
  // Archived projects still render their name on a booking that references
  // them (see the project_name_link column above), but must not be offered
  // as a filter choice — same reasoning as ReleaseList's identical hook use.
  // Not `state.project.projects`: that slice would be shared (and raced)
  // with BookingForm's own dialog, which this page renders unconditionally.
  const { projects, truncated: projectsTruncated } = useAllProjects();

  const grid = useServerGrid({
    endpoint: 'bookings',
    // `booking_status`, not `status` — the wire name differs from the label.
    filterKeys: ['booking_status', 'project_id'],
    onFetch: (params) =>
      dispatch(fetchBookings({ ...params, project_id: apiProjectId(params.project_id) })),
    total,
    totalPending: listLoading,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  );

  // Kebab menu state: tracks which row's menu is open and the anchor element
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; rowId: number } | null>(null);

  // Per-row transition cache keyed by booking id
  const [transitionCache, setTransitionCache] = useState<Record<number, AllowedTransition[]>>({});

  // Transition error state for local error feedback
  const [transitionError, setTransitionError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchDefinitions('booking'));
  }, [dispatch]);

  // --- Kebab menu handlers ---

  const handleMenuOpen = async (el: HTMLElement, rowId: number) => {
    setMenuAnchor({ el, rowId });
    // Lazily fetch transitions if not cached
    if (!(rowId in transitionCache)) {
      try {
        const transitions = await bookingService.getAllowedTransitions(rowId);
        setTransitionCache((prev) => ({ ...prev, [rowId]: transitions }));
      } catch {
        setTransitionCache((prev) => ({ ...prev, [rowId]: [] }));
      }
    }
  };

  const handleMenuClose = () => {
    setMenuAnchor(null);
  };

  const handleOpenDetail = (rowId: number) => {
    handleMenuClose();
    navigate(`/bookings/${rowId}`);
  };

  const handleTransition = async (rowId: number, toState: string) => {
    handleMenuClose();
    // Invalidate cache entry so next open re-fetches fresh transitions
    setTransitionCache((prev) => {
      const next = { ...prev };
      delete next[rowId];
      return next;
    });
    try {
      await bookingService.transitionState(rowId, toState);
      // Re-issue the *current* page/sort/filter query, not a bare unfiltered
      // fetch — the grid is now server-paged, and a plain dispatch(fetchBookings())
      // would silently replace it with the endpoint's defaults.
      grid.refetch();
    } catch (err: unknown) {
      setTransitionError(formatApiError(err, 'Transition failed'));
    }
  };

  // --- Column visibility ---

  const handleColumnVisibilityChange = (model: GridColumnVisibilityModel) => {
    setColumnVisibilityModel(model);
    saveColumnModel(user?.id, model);
  };

  // --- Columns ---

  const columns: GridColDef<BookingResponse>[] = [
    ...bookingColumns.map((col) =>
      col.field === 'actions'
        ? {
            ...col,
            renderCell: ({ row }: GridRenderCellParams<BookingResponse>) => (
              <IconButton
                size="small"
                onClick={(e) => handleMenuOpen(e.currentTarget, row.id)}
                aria-label="row actions"
              >
                <MoreVertIcon fontSize="small" />
              </IconButton>
            ),
          }
        : col
    ),
    ...buildCustomFieldColumns(customFieldDefs),
  ];

  // Only show loading overlay on initial load
  const isInitialLoading = listLoading && bookings.length === 0;

  // Transitions for the currently open menu row
  const activeTransitions = menuAnchor ? (transitionCache[menuAnchor.rowId] ?? null) : null;

  return (
    <Box sx={{ p: 3 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary" sx={{ mr: 1 }}>
          Status:
        </Typography>
        {STATUS_OPTIONS.map((opt) => (
          <Chip
            key={opt.value}
            label={opt.label}
            clickable
            color={(grid.filters.booking_status ?? 'all') === opt.value ? 'primary' : 'default'}
            variant={(grid.filters.booking_status ?? 'all') === opt.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('booking_status', opt.value)}
            size="small"
          />
        ))}
        <TextField
          select
          label="Project"
          size="small"
          value={grid.filters.project_id ?? 'any'}
          onChange={(e) => grid.setFilter('project_id', e.target.value)}
          sx={{ minWidth: 180 }}
          // Never disabled while a filter value is set — a stale or archived
          // `project_id` from a bookmarked/shared link must stay visible and
          // clearable, not vanish behind a disabled, blank select. Only
          // disable for the genuinely-empty case: no projects to filter by
          // and no filter currently applied.
          disabled={projects.length === 0 && !grid.filters.project_id}
          helperText={
            projectsTruncated ? `Only the first ${projects.length} projects are shown.` : undefined
          }
        >
          <MenuItem value="any">All projects</MenuItem>
          {/* The filtered project may not be in the active list — archived
              since the link was made, or every project archived/unfetchable
              (an empty `projects`). Rendering nothing here would strand the
              filter: the grid stays filtered to it (see apiProjectId), the
              select shows blank, and — combined with the old `disabled`
              condition above — was sometimes unclearable without hand-editing
              the URL. Same carve-out shape as ReleaseForm's archived Owning
              project MenuItem. */}
          {grid.filters.project_id &&
            grid.filters.project_id !== 'any' &&
            !projects.some((p) => String(p.id) === grid.filters.project_id) && (
              <MenuItem value={grid.filters.project_id}>
                {`Project #${grid.filters.project_id} (unavailable)`}
              </MenuItem>
            )}
          {projects.map((p) => (
            <MenuItem key={p.id} value={String(p.id)}>{p.name}</MenuItem>
          ))}
        </TextField>
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" size="small" onClick={() => setFormOpen(true)}>
          + New Booking
        </Button>
      </Box>

      {/* Error */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {/* Transition Error */}
      {transitionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setTransitionError(null)}>
          {transitionError}
        </Alert>
      )}

      {/* DataGrid */}
      <DataGrid
        rows={bookings}
        columns={columns}
        loading={isInitialLoading}
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

      {/* Per-row kebab menu */}
      <Menu anchorEl={menuAnchor?.el} open={Boolean(menuAnchor)} onClose={handleMenuClose}>
        <MenuItem onClick={() => menuAnchor && handleOpenDetail(menuAnchor.rowId)}>Open</MenuItem>
        {activeTransitions && activeTransitions.length > 0 && <Divider />}
        {activeTransitions === null && <MenuItem disabled>Loading...</MenuItem>}
        {activeTransitions?.map((t) => (
          <MenuItem
            key={t.to_state}
            onClick={() => menuAnchor && handleTransition(menuAnchor.rowId, t.to_state)}
          >
            {t.label}
          </MenuItem>
        ))}
      </Menu>

      {/* New Booking dialog */}
      <BookingForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        // Re-issue the current page/sort/filter query on create, same reason
        // as handleTransition above — not a bare dispatch(fetchBookings()).
        onCreated={() => grid.refetch()}
      />
    </Box>
  );
}
