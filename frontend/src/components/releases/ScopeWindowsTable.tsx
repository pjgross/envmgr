/**
 * ScopeWindowsTable — releases for a system with their scope cutoff status.
 *
 * Paging, sorting and the window/kind/system filters are all server-side. The
 * "actionable" window filter is three comparisons in SQL (`actual_date IS NULL
 * AND scope_deadline IS NOT NULL AND scope_deadline > now`), so the footer
 * total describes the whole filtered set rather than a truncated page.
 *
 * Fetches into local state rather than Redux so it never clobbers the shared
 * release list — which, since the C3 conversion, holds whichever filtered page
 * ReleaseList is currently showing. That also means `onFetch` returns void, so
 * this table does not get the hook's abort-on-supersede.
 */
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Chip, MenuItem, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import ComputedColumnHeader from '../ComputedColumnHeader';
import { releaseService } from '../../services/releaseService';
import { useAllSystems } from '../../hooks/useAllSystems';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { ReleaseListItemResponse } from '../../types/release';

const WINDOW_COLORS: Record<string, 'default' | 'success' | 'warning' | 'info'> = {
  open: 'success',
  closing_soon: 'warning',
  closed: 'default',
  shipped: 'info',
  no_cutoff: 'default',
};

const WINDOW_LABELS: Record<string, string> = {
  open: 'Open',
  closing_soon: 'Closing soon',
  closed: 'Closed',
  shipped: 'Shipped',
  no_cutoff: 'No cutoff',
};

/**
 * Exported so the column flags can be asserted directly. The grid virtualises
 * columns by container width, which is zero in jsdom, so most headers never
 * render and cannot be queried through the DOM.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const scopeWindowColumns: GridColDef<ReleaseListItemResponse>[] = [
  { field: 'name', headerName: 'Release', flex: 1, minWidth: 180 },
  {
    field: 'systems',
    headerName: 'Systems',
    width: 200,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Systems" />,
    renderCell: (params) => (
      <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap' }}>
        {params.row.systems.length === 0 ? (
          <Typography variant="body2" color="text.secondary">—</Typography>
        ) : (
          params.row.systems.map((s) => (
            <Chip key={s.id} label={s.name} size="small" variant="outlined" />
          ))
        )}
      </Stack>
    ),
  },
  { field: 'release_type', headerName: 'Type', width: 110 },
  { field: 'status', headerName: 'Status', width: 120 },
  {
    field: 'target_date',
    headerName: 'Target',
    width: 120,
    valueFormatter: (params) =>
      params.value ? new Date(params.value as string).toLocaleDateString() : '—',
  },
  {
    // The cutoff ordering lives here. Sorting by the deadline IS sorting by
    // days-to-cutoff — the latter is `(deadline - now).days` for a fixed now,
    // so the two are monotonic in each other — and the server's sort key folds
    // shipped releases into the same NULL bucket as releases with no cutoff,
    // so both group at the end on ascending exactly as they used to.
    field: 'scope_deadline',
    headerName: 'Scope deadline',
    width: 140,
    valueFormatter: (params) =>
      params.value ? new Date(params.value as string).toLocaleDateString() : '—',
  },
  {
    field: 'window_status',
    headerName: 'Window',
    width: 130,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Window" />,
    renderCell: (params) => (
      <Chip
        size="small"
        label={WINDOW_LABELS[params.row.window_status] ?? params.row.window_status}
        color={WINDOW_COLORS[params.row.window_status] ?? 'default'}
      />
    ),
  },
  {
    // Computed in Python after the query, so there is no column to order by.
    // Sort the adjacent Scope deadline header for the same ordering.
    field: 'days_to_cutoff',
    headerName: 'Days to cutoff',
    width: 130,
    align: 'center',
    headerAlign: 'center',
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Days to cutoff" />,
    renderCell: (params) =>
      params.row.days_to_cutoff === null ? (
        <Typography variant="body2" color="text.secondary">—</Typography>
      ) : (
        <Typography variant="body2">{params.row.days_to_cutoff}</Typography>
      ),
  },
  {
    field: 'scope_count',
    headerName: 'Scope',
    width: 90,
    align: 'center',
    headerAlign: 'center',
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Scope" />,
  },
  {
    field: 'scope_creep_count',
    headerName: 'Creep',
    width: 90,
    align: 'center',
    headerAlign: 'center',
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Creep" />,
    renderCell: (params) =>
      params.row.scope_creep_count > 0 ? (
        <Chip label={params.row.scope_creep_count} color="warning" size="small" />
      ) : (
        <Typography variant="body2" color="text.secondary">—</Typography>
      ),
  },
];

/**
 * The URL spells "no window filter" as `any`, never `all`.
 *
 * `all` is `buildParams`' "no selection" sentinel and is dropped from the
 * request — so both states of this toggle would build byte-identical params,
 * and the fetch effect, which keys on the resolved params, would never
 * refetch. `any` survives to the request and is translated here, at the one
 * boundary where the API's own vocabulary applies.
 *
 * An absent value is this table's default rather than "no filter": it opens on
 * the actionable worklist, which is the whole point of the page.
 */
function apiScopeWindow(urlValue: string | number | undefined): 'actionable' | 'all' {
  return urlValue === 'any' ? 'all' : 'actionable';
}

/** This table opens on the soonest cutoff, not the endpoint's created_at/desc. */
const DEFAULT_SORT = { field: 'scope_deadline', dir: 'asc' } as const;

interface Props {
  /** When set, the table is fixed to this system and the system filter is hidden. */
  systemId?: number;
  /** Show the system dropdown (global page). Ignored when systemId is set. */
  showSystemFilter?: boolean;
}

export default function ScopeWindowsTable({ systemId, showSystemFilter }: Props) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ReleaseListItemResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  // Not the shared systems slice: since the C3 conversion that slice holds
  // SystemCatalog's current filtered page, so this dropdown would silently
  // offer a subset.
  const { systems, truncated: systemsTruncated } = useAllSystems();

  const grid = useServerGrid({
    endpoint: 'releases',
    filterKeys: ['scope_window', 'release_kind', 'system_id'],
    defaultSort: DEFAULT_SORT,
    onFetch: (params) => {
      setLoading(true);
      releaseService
        .list({
          ...params,
          // A fixed systemId is a prop, not a user choice, so it overrides the
          // URL filter rather than being written into it.
          ...(systemId ? { system_id: systemId } : {}),
          scope_window: apiScopeWindow(params.scope_window),
        })
        .then(({ rows: r, total: t }) => {
          setRows(r);
          setTotal(t);
        })
        .catch(() => {
          setRows([]);
          setTotal(0);
        })
        .finally(() => setLoading(false));
    },
    total,
    totalPending: loading,
  });

  // The URL is the source of truth; these are the defaults when it is silent.
  const windowFilter = grid.filters.scope_window || 'actionable';
  const kindFilter = grid.filters.release_kind || 'project';
  const selectedSystem = grid.filters.system_id || '';

  const columns = useMemo(() => scopeWindowColumns, []);

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        {showSystemFilter && !systemId && (
          <TextField
            select
            label="System"
            size="small"
            value={selectedSystem}
            onChange={(e) => grid.setFilter('system_id', e.target.value)}
            sx={{ minWidth: 220 }}
            helperText={
              systemsTruncated ? `Only the first ${systems.length} systems are shown.` : undefined
            }
          >
            <MenuItem value="">All systems</MenuItem>
            {systems.map((s) => (
              <MenuItem key={s.id} value={String(s.id)}>{s.name}</MenuItem>
            ))}
          </TextField>
        )}
        <ToggleButtonGroup
          value={kindFilter}
          exclusive
          size="small"
          onChange={(_, v) => v && grid.setFilter('release_kind', v)}
          aria-label="Release kind filter"
        >
          <ToggleButton value="project">Project</ToggleButton>
          <ToggleButton value="enterprise">Enterprise</ToggleButton>
          <ToggleButton value="all">All</ToggleButton>
        </ToggleButtonGroup>
        <ToggleButtonGroup
          value={windowFilter}
          exclusive
          size="small"
          onChange={(_, v) => v && grid.setFilter('scope_window', v)}
          aria-label="Window filter"
        >
          <ToggleButton value="actionable">Open / closing soon</ToggleButton>
          <ToggleButton value="any">All</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Box sx={{ height: 560, width: '100%' }}>
        <DataTable<ReleaseListItemResponse>
          storageKey="scope-windows-table"
          rows={rows}
          columns={columns}
          loading={loading}
          emptyMessage="No releases with scope windows"
          onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
          rowCount={total}
          paginationMode="server"
          sortingMode="server"
          paginationModel={grid.paginationModel}
          onPaginationModelChange={grid.onPaginationModelChange}
          sortModel={grid.sortModel}
          onSortModelChange={grid.onSortModelChange}
          pageSizeOptions={[10, 25, 50, 100]}
        />
      </Box>
    </Box>
  );
}
