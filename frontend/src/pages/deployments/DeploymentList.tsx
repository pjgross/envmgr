import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeployments } from '../../store/deploymentSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { DeploymentStatus } from '../../types/deployment';

const STATUS_OPTIONS: DeploymentStatus[] = [
  'pending', 'in_progress', 'success', 'failed', 'rolled_back',
];

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "deployments"): status, deployer_name, deployed_at. The other four columns are
// joined or derived (environment_name, build_sha_short, release_name,
// change_request_title) — none is backed by a single column the database could
// order by, so they never were and never can be sortable.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file).
// eslint-disable-next-line react-refresh/only-export-components
export const deploymentColumns: GridColDef[] = [
  { field: 'environment_name', headerName: 'Environment', width: 180, sortable: false },
  { field: 'build_sha_short', headerName: 'Build', width: 110, sortable: false },
  {
    field: 'status', headerName: 'Status', width: 140,
    renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
  },
  { field: 'deployer_name', headerName: 'Deployer', flex: 1 },
  { field: 'deployed_at', headerName: 'Deployed at', width: 200 },
  { field: 'release_name', headerName: 'Release', width: 160, sortable: false },
  { field: 'change_request_title', headerName: 'Change request', width: 200, sortable: false },
];

export default function DeploymentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, total, listLoading } = useSelector((s: RootState) => s.deployment);

  const grid = useServerGrid({
    endpoint: 'deployments',
    filterKeys: ['status', 'environment_search', 'release_search'],
    // Free-text keys. This list is also the 'all'-sentinel exemption list —
    // every entry must appear in filterKeys above.
    debounceKeys: ['environment_search', 'release_search'],
    onFetch: (params) => dispatch(fetchDeployments(params)),
    total,
    totalPending: listLoading,
  });

  const rows = items.map((d) => ({
    id: d.id,
    environment_name: d.environment_name ?? '—',
    build_sha_short: d.build_sha_short ?? '—',
    status: d.status,
    deployer_name: d.deployer_name ?? '—',
    deployed_at: new Date(d.deployed_at).toLocaleString(),
    release_name: d.release_name ?? '—',
    change_request_title: d.change_request_title ?? '—',
  }));

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Deployments</Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="Environment"
            value={grid.filters.environment_search ?? ''}
            onChange={(e) => grid.setFilter('environment_search', e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            size="small" label="Release"
            value={grid.filters.release_search ?? ''}
            onChange={(e) => grid.setFilter('release_search', e.target.value)}
            sx={{ width: 200 }}
          />
          <TextField
            select size="small" label="Status"
            value={grid.filters.status ?? ''}
            onChange={(e) => grid.setFilter('status', e.target.value)}
            sx={{ width: 160 }}
          >
            <MenuItem value="">Any</MenuItem>
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>{s}</MenuItem>
            ))}
          </TextField>
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={rows}
          columns={deploymentColumns}
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
          onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
