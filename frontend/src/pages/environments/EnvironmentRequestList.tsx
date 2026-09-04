/**
 * EnvironmentRequestList — the team queue for environment-request triage.
 *
 * All / Mine / For my team are one filter, not three, because at most one of
 * `mine`/`actionable` is ever sent — the backend computes `actionable` from
 * role + group membership (see environment_request_service's `actionable`
 * definition), and it is a distinct query shape from `mine`, not a client-side
 * refinement of it.
 */
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, Button, Chip } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import AddIcon from '@mui/icons-material/Add';

import type { AppDispatch, RootState } from '../../store';
import { fetchEnvironmentRequests } from '../../store/environmentRequestSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { EnvironmentRequestResponse } from '../../types/environmentRequest';
import PageHeader from '../../components/layout/PageHeader';

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "environment-requests" and the backend's REQUEST_SORTS): status, kind,
// needed_by, created_at ONLY. `target` is computed from two columns
// (environment_name for an access request, proposed_name for a
// new-environment one), and requester_username is joined — neither is backed
// by a single column, so neither can be whitelisted. A sortable header on
// them would look clickable and 422 on click.
// eslint-disable-next-line react-refresh/only-export-components
export const environmentRequestColumns: GridColDef<EnvironmentRequestResponse>[] = [
  {
    field: 'target',
    headerName: 'Target',
    flex: 1,
    sortable: false,
    valueGetter: (params) =>
      params.row.kind === 'access'
        ? (params.row.environment_name ?? '—')
        : `${params.row.proposed_name ?? '—'} (new)`,
  },
  {
    field: 'kind',
    headerName: 'Kind',
    width: 150,
    // M6: matches the detail page's rendering of the same field — the grid
    // was the only place in the app still showing the raw 'access' /
    // 'new_environment' literal.
    valueFormatter: (params) =>
      params.value === 'access' ? 'Access' : 'New environment',
  },
  { field: 'requester_username', headerName: 'Requested by', width: 160, sortable: false },
  { field: 'status', headerName: 'Status', width: 130 },
  {
    field: 'needed_by',
    headerName: 'Needed by',
    width: 140,
    // M6: matches the detail page's `new Date(...).toLocaleDateString()` —
    // the grid was showing the raw ISO timestamp.
    valueFormatter: (params) =>
      params.value ? new Date(params.value as string).toLocaleDateString() : '—',
  },
];

type QueueFilter = 'any' | 'mine' | 'team';

const QUEUE_FILTERS: { label: string; value: QueueFilter }[] = [
  { label: 'All', value: 'any' },
  { label: 'Mine', value: 'mine' },
  { label: 'For my team', value: 'team' },
];

/**
 * The URL spells "no queue filter" as `any`, never `all`: `all` is
 * `buildParams`' own "no selection" sentinel and would be dropped from the
 * request, so both "no filter" and a hypothetical literal `all` selection
 * would build byte-identical params and the grid would never refetch — the
 * exact hazard `ScopeWindowsTable`'s `apiScopeWindow` exists to avoid, and
 * documented in docs/pagination.md. `any` survives to this boundary, where it
 * is translated into the API's own vocabulary (`mine` / `actionable`).
 */
function queueParams(value: string | undefined): { mine?: true; actionable?: true } {
  if (value === 'mine') return { mine: true };
  if (value === 'team') return { actionable: true };
  return {};
}

export default function EnvironmentRequestList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { requests, total, loading, error } = useSelector(
    (state: RootState) => state.environmentRequest
  );

  const grid = useServerGrid({
    endpoint: 'environment-requests',
    filterKeys: ['queue'],
    onFetch: (params) =>
      dispatch(
        fetchEnvironmentRequests({
          limit: params.limit,
          offset: params.offset,
          sort_by: params.sort_by,
          sort_dir: params.sort_dir,
          ...queueParams(params.queue as string | undefined),
        })
      ),
    total,
    totalPending: loading,
  });

  // The URL, read back on every mount — not local component state — so a
  // reload or a shared link reproduces the same queue rather than silently
  // resetting to "All".
  const queueFilter = grid.filters.queue ?? 'any';

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Environment requests"
        actions={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate('/environment-requests/new')}
          >
            New Request
          </Button>
        }
      />

      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {QUEUE_FILTERS.map((f) => (
          <Chip
            key={f.value}
            label={f.label}
            clickable
            color={queueFilter === f.value ? 'primary' : 'default'}
            variant={queueFilter === f.value ? 'filled' : 'outlined'}
            onClick={() => grid.setFilter('queue', f.value)}
          />
        ))}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <DataGrid
        rows={requests}
        columns={environmentRequestColumns}
        loading={loading && requests.length === 0}
        onRowClick={(params) => navigate(`/environment-requests/${params.row.id}`)}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        // `rows` is one windowed page, not the whole result set — see
        // EnvironmentList's identical guard and docs/pagination.md.
        disableColumnFilter
        paginationModel={grid.paginationModel}
        onPaginationModelChange={grid.onPaginationModelChange}
        sortModel={grid.sortModel}
        onSortModelChange={grid.onSortModelChange}
        pageSizeOptions={[10, 25, 50, 100]}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />
    </Box>
  );
}
