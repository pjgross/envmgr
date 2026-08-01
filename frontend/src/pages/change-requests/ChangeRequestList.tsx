import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import ComputedColumnHeader from '../../components/ComputedColumnHeader';
import { AppDispatch, RootState } from '../../store';
import { fetchChangeRequests } from '../../store/changeRequestSlice';
import { fetchEnvironments } from '../../store/environmentSlice';
import { fetchInfrastructureComponents } from '../../store/infrastructureComponentSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import ChangeRequestForm from './ChangeRequestForm';
import {
  CHANGE_TYPE_LABELS,
  type ChangeRequestResponse,
  type ChangeType,
} from '../../types/changeRequest';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  in_progress: 'info',
  completed: 'info',
};

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "change-requests"): title, change_type, status, scheduled_start. `id` is in no
// endpoint's whitelist, and environments/hosts/has_outage are computed after the
// page is fetched — none is backed by a single column the database could order
// by, so none ever was or can be sortable.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file).
// eslint-disable-next-line react-refresh/only-export-components
export const changeRequestColumns: GridColDef<ChangeRequestResponse>[] = [
  { field: 'id', headerName: 'ID', width: 80, sortable: false },
  {
    field: 'title',
    headerName: 'Title',
    flex: 1,
    minWidth: 200,
  },
  {
    field: 'change_type',
    headerName: 'Type',
    width: 150,
    valueGetter: (params) => CHANGE_TYPE_LABELS[params.row.change_type as ChangeType] ?? params.row.change_type,
  },
  {
    field: 'status',
    headerName: 'Status',
    width: 130,
    renderCell: (params) => (
      <Chip
        label={params.row.status}
        color={STATUS_COLORS[params.row.status] ?? 'default'}
        size="small"
      />
    ),
  },
  {
    field: 'environments',
    headerName: 'Environments',
    width: 220,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Environments" />,
    renderCell: (params) => {
      const envs = params.row.environments ?? [];
      const derived = new Set(params.row.derived_environment_ids ?? []);
      const first = envs[0];
      if (!first && derived.size === 0) return <Typography variant="body2" color="text.secondary">—</Typography>;
      const extraCount = Math.max(0, envs.length - 1);
      const derivedCount = derived.size;
      return (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          {first && <Chip size="small" label={first.name} />}
          {extraCount > 0 && <Chip size="small" label={`+${extraCount}`} variant="outlined" />}
          {derivedCount > 0 && (
            <Chip
              size="small"
              label={`+${derivedCount} derived`}
              color="info"
              variant="outlined"
            />
          )}
        </Box>
      );
    },
  },
  {
    field: 'hosts',
    headerName: 'Hosts',
    width: 200,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Hosts" />,
    renderCell: (params) => {
      const hostList = params.row.hosts ?? [];
      if (hostList.length === 0)
        return (
          <Typography variant="body2" color="text.secondary">
            —
          </Typography>
        );
      const first = hostList[0];
      const extraCount = Math.max(0, hostList.length - 1);
      return (
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
          <Chip size="small" label={first.name} />
          {extraCount > 0 && <Chip size="small" label={`+${extraCount}`} variant="outlined" />}
        </Box>
      );
    },
  },
  {
    field: 'has_outage',
    headerName: 'Outage',
    width: 90,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Outage" />,
    renderCell: (params) =>
      params.row.has_outage ? <Chip label="Outage" size="small" color="error" /> : null,
  },
  {
    field: 'scheduled_start',
    headerName: 'Scheduled',
    width: 180,
    valueGetter: (params) => new Date(params.row.scheduled_start),
    valueFormatter: (params) =>
      params.value instanceof Date ? params.value.toLocaleString() : '',
  },
];

export default function ChangeRequestList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, total, listLoading } = useSelector((s: RootState) => s.changeRequest);
  const environments = useSelector((s: RootState) => s.environment.environments);
  const hosts = useSelector((s: RootState) => s.infrastructureComponent.components);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [formOpen, setFormOpen] = useState(false);

  const grid = useServerGrid({
    endpoint: 'change-requests',
    filterKeys: ['status', 'environment_id', 'host_id'],
    onFetch: (params) => dispatch(fetchChangeRequests(params)),
    total,
    totalPending: listLoading,
  });

  useEffect(() => {
    dispatch(fetchEnvironments());
    dispatch(fetchInfrastructureComponents());
  }, [dispatch]);

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Change Requests
        </Typography>
        <Button variant="contained" onClick={() => setFormOpen(true)}>
          New Change Request
        </Button>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <TextField
          select
          label="Status"
          size="small"
          value={grid.filters.status ?? 'all'}
          onChange={(e) => grid.setFilter('status', e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          <MenuItem value="draft">Draft</MenuItem>
          <MenuItem value="submitted">Submitted</MenuItem>
          <MenuItem value="approved">Approved</MenuItem>
          <MenuItem value="rejected">Rejected</MenuItem>
          <MenuItem value="in_progress">In Progress</MenuItem>
          <MenuItem value="completed">Completed</MenuItem>
        </TextField>
        <TextField
          select
          label="Environment"
          size="small"
          value={grid.filters.environment_id ?? 'all'}
          onChange={(e) => grid.setFilter('environment_id', e.target.value)}
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="all">All</MenuItem>
          {environments.map((e) => (
            <MenuItem key={e.id} value={String(e.id)}>
              {e.name}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Host"
          size="small"
          value={grid.filters.host_id ?? 'all'}
          onChange={(e) => grid.setFilter('host_id', e.target.value)}
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="all">All</MenuItem>
          {hosts.map((h) => (
            <MenuItem key={h.id} value={String(h.id)}>
              {h.name}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      <Box sx={{ height: 600, width: '100%' }}>
        <DataTable<ChangeRequestResponse>
          storageKey="change-requests-list"
          userId={currentUserId}
          rows={list}
          columns={changeRequestColumns}
          loading={listLoading}
          rowCount={total}
          paginationMode="server"
          sortingMode="server"
          paginationModel={grid.paginationModel}
          onPaginationModelChange={grid.onPaginationModelChange}
          sortModel={grid.sortModel}
          onSortModelChange={grid.onSortModelChange}
          pageSizeOptions={[10, 25, 50, 100]}
          emptyMessage="No change requests yet"
          onRowClick={(params) => navigate(`/change-requests/${params.row.id}`)}
        />
      </Box>

      <ChangeRequestForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        // Re-issue the current page/sort/filter query on create — not a bare
        // dispatch(fetchChangeRequests()), which would clobber the current
        // view with the endpoint's unfiltered page-1 default. See
        // ChangeRequestForm's onCreated JSDoc and changeRequestSlice's
        // comment on createChangeRequest.fulfilled.
        onCreated={() => grid.refetch()}
      />
    </Box>
  );
}
