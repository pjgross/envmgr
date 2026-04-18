import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Chip, MenuItem, TextField, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { AppDispatch, RootState } from '../../store';
import { fetchChangeRequests } from '../../store/changeRequestSlice';
import { fetchEnvironments } from '../../store/environmentSlice';
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
  const { list, loading } = useSelector((s: RootState) => s.changeRequest);
  const environments = useSelector((s: RootState) => s.environment.environments);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [envFilter, setEnvFilter] = useState<number | 'all'>('all');
  const [formOpen, setFormOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchChangeRequests({}));
    dispatch(fetchEnvironments());
  }, [dispatch]);

  const filteredRows = useMemo(
    () =>
      list.filter((cr) => {
        if (statusFilter !== 'all' && cr.status !== statusFilter) return false;
        if (envFilter !== 'all' && cr.environment_id !== envFilter) return false;
        return true;
      }),
    [list, statusFilter, envFilter]
  );

  const envNameById = useMemo(
    () => Object.fromEntries(environments.map((e) => [e.id, e.name])),
    [environments]
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
        field: 'environment_id',
        headerName: 'Environment',
        width: 160,
        valueGetter: (params) => envNameById[params.row.environment_id] ?? `#${params.row.environment_id}`,
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
    [envNameById]
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
      </Box>

      <Box sx={{ height: 600, width: '100%' }}>
        <DataTable<ChangeRequestResponse>
          storageKey="change-requests-list"
          userId={currentUserId}
          rows={filteredRows}
          columns={columns}
          loading={loading}
          emptyMessage="No change requests yet"
          onRowClick={(params) => navigate(`/change-requests/${params.row.id}`)}
        />
      </Box>

      <ChangeRequestForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  );
}
