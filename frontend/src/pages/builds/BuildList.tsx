import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Paper, Stack, TextField } from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchBuilds } from '../../store/buildSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import ComputedColumnHeader from '../../components/ComputedColumnHeader';
import type { PipelineStep } from '../../types/build';
import PageHeader from '../../components/layout/PageHeader';

function latestStepSummary(steps: PipelineStep[]): string {
  if (steps.length === 0) return '—';
  const last = steps[steps.length - 1];
  return `${last.name} (${last.status})`;
}

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "builds"): git_branch, build_number, commit_timestamp. The other three columns
// are joined or derived (subsystem_name, git_sha_short, release_name) — none is
// backed by a single column the database could order by, so none ever was or can
// be sortable. latest_step is additionally computed in the browser from each
// row's pipeline_steps JSON, so it gets the explanatory ComputedColumnHeader
// rather than a header that just silently stops working.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file).
// eslint-disable-next-line react-refresh/only-export-components
export const buildColumns: GridColDef[] = [
  { field: 'subsystem_name', headerName: 'SubSystem', width: 180, sortable: false },
  { field: 'git_branch', headerName: 'Branch', width: 160 },
  { field: 'git_sha_short', headerName: 'SHA', width: 100, sortable: false },
  { field: 'build_number', headerName: 'Build #', width: 100 },
  { field: 'release_name', headerName: 'Release', width: 160, sortable: false },
  { field: 'commit_timestamp', headerName: 'Commit at', width: 200 },
  {
    field: 'latest_step',
    headerName: 'Latest step',
    flex: 1,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Latest step" />,
  },
];

export default function BuildList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, total, listLoading } = useSelector((s: RootState) => s.build);

  const grid = useServerGrid({
    endpoint: 'builds',
    filterKeys: ['subsystem_search', 'branch', 'date_from', 'date_to'],
    // Free-text keys, and also the 'all'-sentinel exemption list. `branch`
    // belongs here because it is typed character by character — today it
    // fires a request per keystroke.
    debounceKeys: ['subsystem_search', 'branch'],
    onFetch: (params) => dispatch(fetchBuilds(params)),
    total,
    totalPending: listLoading,
  });

  const rows = items.map((b) => ({
    id: b.id,
    subsystem_name: b.subsystem_name ?? '—',
    git_sha_short: b.git_sha.slice(0, 8),
    git_branch: b.git_branch ?? '—',
    build_number: b.build_number ?? '—',
    release_name: b.release_name ?? '—',
    commit_timestamp: new Date(b.commit_timestamp).toLocaleString(),
    latest_step: latestStepSummary(b.pipeline_steps),
  }));

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader title="Builds" />

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="SubSystem"
            value={grid.filters.subsystem_search ?? ''}
            onChange={(e) => grid.setFilter('subsystem_search', e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            size="small" label="Branch"
            value={grid.filters.branch ?? ''}
            onChange={(e) => grid.setFilter('branch', e.target.value)}
            sx={{ width: 180 }}
          />
          <TextField
            size="small" label="From" type="date"
            value={grid.filters.date_from ? grid.filters.date_from.slice(0, 10) : ''}
            onChange={(e) => {
              const v = e.target.value;
              grid.setFilter(
                'date_from',
                v ? new Date(`${v}T00:00:00Z`).toISOString() : ''
              );
            }}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            size="small" label="To" type="date"
            value={grid.filters.date_to ? grid.filters.date_to.slice(0, 10) : ''}
            onChange={(e) => {
              const v = e.target.value;
              grid.setFilter(
                'date_to',
                v ? new Date(`${v}T23:59:59Z`).toISOString() : ''
              );
            }}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={rows}
          columns={buildColumns}
          autoHeight
          loading={listLoading}
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
          onRowClick={(p: GridRowParams) => navigate(`/builds/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
