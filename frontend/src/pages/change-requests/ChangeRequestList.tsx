import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { AppDispatch, RootState } from '../../store';
import { fetchChangeRequests } from '../../store/changeRequestSlice';
import { fetchEnvironments } from '../../store/environmentSlice';
import { fetchInfrastructureComponents } from '../../store/infrastructureComponentSlice';
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

export default function ChangeRequestList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, listLoading } = useSelector((s: RootState) => s.changeRequest);
  const environments = useSelector((s: RootState) => s.environment.environments);
  const hosts = useSelector((s: RootState) => s.infrastructureComponent.components);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [envFilter, setEnvFilter] = useState<number | 'all'>('all');
  const [hostFilter, setHostFilter] = useState<number | 'all'>('all');
  const [formOpen, setFormOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchChangeRequests({}));
    dispatch(fetchEnvironments());
    dispatch(fetchInfrastructureComponents());
  }, [dispatch]);

  const filteredRows = useMemo(
    () =>
      list.filter((cr) => {
        if (statusFilter !== 'all' && cr.status !== statusFilter) return false;
        if (envFilter !== 'all' && !cr.environment_ids.includes(envFilter)) return false;
        if (hostFilter !== 'all' && !cr.host_ids.includes(hostFilter)) return false;
        return true;
      }),
    [list, statusFilter, envFilter, hostFilter]
  );

  const columns = useMemo<GridColDef<ChangeRequestResponse>[]>(
    () => [
      { field: 'id', headerName: 'ID', width: 80 },
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
    ],
    []
  );

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
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
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
          value={envFilter}
          onChange={(e) =>
            setEnvFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))
          }
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="all">All</MenuItem>
          {environments.map((e) => (
            <MenuItem key={e.id} value={e.id}>
              {e.name}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Host"
          size="small"
          value={hostFilter}
          onChange={(e) =>
            setHostFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))
          }
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="all">All</MenuItem>
          {hosts.map((h) => (
            <MenuItem key={h.id} value={h.id}>
              {h.name}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      <Box sx={{ height: 600, width: '100%' }}>
        <DataTable<ChangeRequestResponse>
          storageKey="change-requests-list"
          userId={currentUserId}
          rows={filteredRows}
          columns={columns}
          loading={listLoading}
          emptyMessage="No change requests yet"
          onRowClick={(params) => navigate(`/change-requests/${params.row.id}`)}
        />
      </Box>

      <ChangeRequestForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  );
}
