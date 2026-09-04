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
import AgreementGapIndicator from '../../components/bookings/AgreementGapIndicator';
import { ContentionMarker } from '../../components/bookings/ContentionMarker';
import { formatApiError } from '../../services/apiError';
import BookingForm from './BookingForm';
import PageHeader from '../../components/layout/PageHeader';
import {
  PROTECTION_FILTER_NONE,
  PROTECTION_LABELS,
  PROTECTION_LEVELS,
} from '../../constants/protection';

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

// --- Usage-agreement gap filter (Phase 7 A3) ---------------------------------

/**
 * `?agreement_gap=` on `GET /bookings` — the wire name is exactly this, as
 * declared by `list_bookings` in backend/app/api/v1/bookings.py. FastAPI drops
 * unknown query params silently, so a misspelling here would filter nothing at
 * all while looking entirely correct: `/releases/calendar` sent `from`/`to` at
 * an endpoint declaring `date_from`/`date_to` for months, and the Projects grid
 * linked to a `?project_id=` that no endpoint accepted.
 *
 * Three states, and only two of them travel:
 * - `true`  — only bookings no live usage agreement covers.
 * - `false` — the exact complement: covered bookings, plus those whose request
 *   names no project (so the two partition the estate rather than leaving
 *   project-less bookings invisible to both).
 * - no selection — the key is NOT SENT. Spelled `any` in the URL, never `all`
 *   (`buildParams`' own "no selection" sentinel, which must never be a value
 *   this filter's vocabulary contains) and never `''` (which MUI's Select
 *   renders as a blank box rather than as its own option's label). Mapped to
 *   `undefined` here, and axios omits an undefined param — so nothing can emit
 *   `?agreement_gap=`, which is a **422** from FastAPI's `Optional[bool]`
 *   rather than an ignored param. Same shape, and the same reason, as
 *   `apiProjectId`'s `any` on the select beside it.
 *
 * Everything else — a hand-edited `yes`, `all`, a stale link — is no selection
 * too, rather than a 422 that would blank the grid. Anything read out of the
 * URL is untrusted, exactly as `sort_by` is.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function apiAgreementGap(urlValue: string | number | undefined): boolean | undefined {
  if (urlValue === 'true') return true;
  if (urlValue === 'false') return false;
  return undefined;
}

/** The URL's spelling of "no gap filter" — see apiAgreementGap above. */
const GAP_FILTER_NONE = 'any';

const GAP_FILTER_OPTIONS: Array<{ label: string; value: string }> = [
  { label: 'All bookings', value: GAP_FILTER_NONE },
  // Deliberately not "Unacknowledged" and "Acknowledged": acknowledging a gap
  // does not close it, so both acknowledged and unacknowledged gaps are "In
  // gap" and the server returns both for `agreement_gap=true`. The two states
  // are told apart in the column, not in the filter — there is no server-side
  // filter for the acknowledgement, and inventing one in the browser would
  // filter the loaded page instead of the result set.
  { label: 'In gap', value: 'true' },
  { label: 'No gap', value: 'false' },
];

// --- Protection filter (Phase 7 B4) ------------------------------------------

/**
 * `?protection=` on `GET /bookings` — the wire name is exactly this (the
 * COLUMN is `protection_level`; the QUERY PARAM is not), as declared by
 * `list_bookings` in backend/app/api/v1/bookings.py. FastAPI drops unknown
 * query params silently, so `?protection_level=` would filter nothing at all
 * while looking entirely correct.
 *
 * Three states, and only two of them travel: `soft`, `hard`, and no selection
 * — spelled `any` in the URL, never `all` (`buildParams`' own sentinel, which
 * would make two toggle states build byte-identical params so the grid never
 * refetched) and never `''` (a **422** from the endpoint's
 * `Optional[Literal["soft","hard"]]`, not an ignored param). Anything else —
 * a hand-edited value, a stale link — is no selection too, exactly as
 * `apiAgreementGap` treats its own vocabulary.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function apiProtection(urlValue: string | number | undefined): 'soft' | 'hard' | undefined {
  if (urlValue === 'soft') return 'soft';
  if (urlValue === 'hard') return 'hard';
  return undefined;
}

const PROTECTION_FILTER_OPTIONS: Array<{ label: string; value: string }> = [
  { label: 'All bookings', value: PROTECTION_FILTER_NONE },
  ...PROTECTION_LEVELS.map((level) => ({ label: PROTECTION_LABELS[level], value: level })),
];

// --- Columns -------------------------------------------------------------

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "bookings"): start_date, end_date, status, protection_level. That last one is
// the first addition to this list since the page was converted, and it
// qualifies for the reason none of the others do: it is a real column
// (`booking_request.protection_level`), whitelisted by BOOKING_SORTS, resolved
// by a join the list query already makes — not a value computed after the page
// is fetched. The other columns are joined
// (project_name, project_name_link, environment_name, booked_by_username), a
// per-tenant lookup rendered as a chip (booking_type_id), a per-row kebab
// menu with no backing column (actions), or computed after the page is
// fetched (conflicts, agreement_gap) — none is backed by a single column the
// database could order by, so none ever was or can be sortable. Note
// `agreement_gap` IS a query parameter on the endpoint, but a filter, never a
// sort key: an unknown sort_by is a 422, not a silent fallback.
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
    // Not backed by a single sortable column — resolved via the
    // `environment_group` join the same way `environment_name` is, and
    // deliberately never dropped even though bookings from a group render
    // together on the detail page (GroupTransitionPanel): this list, and its
    // kebab's per-booking transition action, are the surfaces a Test
    // Manager actually approves down. Without this column and the note the
    // kebab menu shows for a group member below, approving row by row here
    // silently diverges a group with nothing on screen to say one exists —
    // Finding 3 of the A2 whole-branch review.
    field: 'environment_group_name',
    headerName: 'Group',
    flex: 0.8,
    sortable: false,
    valueGetter: (params: GridValueGetterParams<BookingResponse>) =>
      params.row.environment_group_name ?? '—',
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
    // B4's protection level. Sortable — unlike every other non-date column
    // here — because it IS a single column the database can order by; see the
    // note above the array.
    //
    // Renders NOTHING when the level is absent rather than defaulting to
    // "Preemptible": `protection_level` is optional on BookingResponse (a
    // Booking has no such attribute; `_to_response` sets it explicitly), so an
    // absent value means "this response did not say", and printing the soft
    // label would state as fact something nobody claimed.
    field: 'protection_level',
    headerName: 'Protection',
    width: 120,
    renderCell: ({ row }) =>
      row.protection_level ? (
        <Chip
          label={PROTECTION_LABELS[row.protection_level]}
          size="small"
          variant="outlined"
          color={row.protection_level === 'hard' ? 'secondary' : 'default'}
        />
      ) : null,
  },
  {
    // A3's usage-agreement warning. Never sortable: `agreement_gap` is a
    // FILTER on GET /bookings, and BOOKING_SORTS whitelists start_date,
    // end_date and status only — an unknown sort_by is a 422, not a silent
    // fallback. The message itself is batch-resolved after the page is
    // fetched (agreement_gap_service.gap_warnings_for_bookings), the same
    // shape as the Conflicts column beside it.
    field: 'agreement_gap',
    headerName: 'Agreement',
    width: 100,
    hideable: false,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Agreement" />,
    renderCell: ({ row }) => (
      <AgreementGapIndicator
        gap={row.agreement_gap}
        // NOT derived from `agreement_gap_ack`, which GET /bookings/{id}
        // alone populates — every list row carries it as null, so a cell
        // reading it would report every gap as unacknowledged.
        hasUnacknowledgedGap={row.has_unacknowledged_agreement_gap}
      />
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
    // B6 — the fold of every live overlapping pair this booking is part of
    // (contention_forecast_service.contention_states_for_bookings), resolved
    // once per response AFTER the page is fetched — the same shape as
    // `agreement_gap` and `conflicts` beside it. Never sortable:
    // `contention_state` is absent from BOOKING_SORTS (backend/app/api/v1/
    // bookings.py), so a bare `?sort_by=contention_state` is a 422, and this
    // page has no `?contention=` filter either — `/contentions` is the
    // filtering surface, and a second filter here would need a second
    // definition of the fold.
    //
    // Renders NOTHING when `contention_state` is null — the common case, not
    // an edge case — never an empty chip; see ContentionMarker's docstring
    // for why the marker itself has no branch for that at all.
    field: 'contention_state',
    headerName: 'Contention',
    width: 200,
    hideable: false,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Contention" />,
    renderCell: ({ row }) =>
      row.contention_state ? (
        <span data-testid="contention-marker">
          <ContentionMarker state={row.contention_state} />
        </span>
      ) : null,
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

// The kebab's transition action must say when transitioning a row alone will
// diverge its group — Finding 3 of the A2 whole-branch review found no
// on-screen sign here that a group even existed. Pulled out to a plain
// function, same reason as `buildCustomFieldColumns` below: @mui/x-data-grid
// virtualizes columns/cells by container width, and jsdom reports zero
// layout width, so a real render of this page never gets the `actions`
// column's kebab button into the DOM for a test to click — this is directly
// unit-testable instead.
// eslint-disable-next-line react-refresh/only-export-components
export function groupDivergenceWarning(
  row: Pick<BookingResponse, 'environment_group_id' | 'environment_group_name'> | null | undefined
): string | null {
  if (!row || row.environment_group_id == null) return null;
  const name = row.environment_group_name ?? `#${row.environment_group_id}`;
  return `In group "${name}" — transitioning here alone will not move the rest of the group.`;
}

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
    filterKeys: ['booking_status', 'project_id', 'agreement_gap', 'protection'],
    onFetch: (params) =>
      dispatch(
        fetchBookings({
          ...params,
          project_id: apiProjectId(params.project_id),
          agreement_gap: apiAgreementGap(params.agreement_gap),
          protection: apiProtection(params.protection),
        })
      ),
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

  // What the gap select displays — resolved through the SAME function that
  // decides what gets sent, so an unrecognised URL value ("yes", "all", a
  // stale link) reads as "All bookings" and sends nothing, rather than
  // rendering a blank select over a grid nobody can explain.
  const gapFilter = apiAgreementGap(grid.filters.agreement_gap);
  const gapFilterValue = gapFilter === undefined ? GAP_FILTER_NONE : String(gapFilter);

  // Same one-source rule for B4's protection select.
  const protectionFilterValue = apiProtection(grid.filters.protection) ?? PROTECTION_FILTER_NONE;

  // Transitions for the currently open menu row
  const activeTransitions = menuAnchor ? (transitionCache[menuAnchor.rowId] ?? null) : null;

  // The row behind the currently open menu — looked up from the loaded page,
  // not a separate fetch, purely to read its group membership for the note
  // below. `bookings` is this page's rows, and the menu can only be open for
  // a row that is currently rendered.
  const menuRow = menuAnchor ? (bookings.find((b) => b.id === menuAnchor.rowId) ?? null) : null;

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Bookings"
        actions={
          <Button variant="contained" size="small" onClick={() => setFormOpen(true)}>
            + New Booking
          </Button>
        }
      />

      {/* Filters */}
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
        {/* A3's usage-agreement gap (see apiAgreementGap above). A filter, not
            a gate: it narrows the list and refuses nothing. The displayed value
            is derived from the same function that builds the request, so a
            stale or hand-edited URL value can never leave the select blank
            while the grid is filtered by something else — one source, not two
            that can disagree. `grid.filters` is the draft-aware value the other
            filters on this page bind to. */}
        <TextField
          select
          label="Usage agreement"
          size="small"
          value={gapFilterValue}
          onChange={(e) => grid.setFilter('agreement_gap', e.target.value)}
          sx={{ minWidth: 170 }}
        >
          {GAP_FILTER_OPTIONS.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>
              {opt.label}
            </MenuItem>
          ))}
        </TextField>
        {/* B4's protection level (see apiProtection above). Runs in SQL, before
            the window, so X-Total-Count describes the filtered set — and it
            narrows the list without refusing anything: B4 advises. */}
        <TextField
          select
          label="Protection"
          size="small"
          value={protectionFilterValue}
          onChange={(e) => grid.setFilter('protection', e.target.value)}
          sx={{ minWidth: 160 }}
        >
          {PROTECTION_FILTER_OPTIONS.map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>
              {opt.label}
            </MenuItem>
          ))}
        </TextField>
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
        {/* This booking is a group member — transitioning it here moves only
            this one row. The group's OTHER members will not follow, which
            diverges the group (see GroupTransitionPanel's out-of-step repair
            path on the booking detail page). Said here, not only there,
            because this menu is the other place a transition actually
            happens. See `groupDivergenceWarning` above for why the text
            itself is a plain function rather than computed inline. */}
        {activeTransitions &&
          activeTransitions.length > 0 &&
          groupDivergenceWarning(menuRow) && (
            <MenuItem disabled divider sx={{ whiteSpace: 'normal', maxWidth: 280 }}>
              <Typography variant="caption" color="text.secondary">
                {groupDivergenceWarning(menuRow)}
              </Typography>
            </MenuItem>
          )}
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
