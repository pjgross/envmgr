import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Button, Chip, MenuItem, TextField, Tooltip, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import BlockIcon from '@mui/icons-material/Block';
import DataTable from '../../components/DataTable';
import { AppDispatch, RootState } from '../../store';
import { fetchReleases } from '../../store/releaseSlice';
import type { ReleaseListItemResponse } from '../../types/release';
import ReleaseForm from './ReleaseForm';

const STATUS_COLORS: Record<string, 'default' | 'success' | 'warning' | 'error' | 'info'> = {
  draft: 'default',
  planning: 'info',
  in_progress: 'info',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  completed: 'success',
  cancelled: 'error',
};

const RELEASE_TYPES = ['project', 'hotfix', 'patch', 'major', 'minor'];

export default function ReleaseList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, loading } = useSelector((s: RootState) => s.release);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [formOpen, setFormOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchReleases({}));
  }, [dispatch]);

  const filteredRows = useMemo(
    () =>
      list.filter((r) => {
        if (statusFilter !== 'all' && r.status !== statusFilter) return false;
        if (typeFilter !== 'all' && r.release_type !== typeFilter) return false;
        return true;
      }),
    [list, statusFilter, typeFilter]
  );

  const columns = useMemo<GridColDef<ReleaseListItemResponse>[]>(
    () => [
      { field: 'id', headerName: 'ID', width: 70 },
      {
        field: 'name',
        headerName: 'Name',
        flex: 1,
        minWidth: 200,
      },
      {
        field: 'release_type',
        headerName: 'Type',
        width: 120,
        renderCell: (params) => (
          <Chip label={params.row.release_type} size="small" variant="outlined" />
        ),
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
        field: 'target_date',
        headerName: 'Target Date',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'phase_count',
        headerName: 'Phases',
        width: 90,
        align: 'center',
        headerAlign: 'center',
      },
      {
        field: 'scope_count',
        headerName: 'Scope',
        width: 90,
        align: 'center',
        headerAlign: 'center',
      },
      {
        field: 'blocker_count',
        headerName: 'Blockers',
        width: 100,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.blocker_count > 0 ? (
            <Tooltip title={`${params.row.blocker_count} pending gate(s)`}>
              <Chip
                icon={<BlockIcon />}
                label={params.row.blocker_count}
                color="warning"
                size="small"
              />
            </Tooltip>
          ) : (
            <Typography variant="body2" color="text.secondary">
              —
            </Typography>
          ),
      },
      {
        field: 'created_at',
        headerName: 'Created',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
    ],
    []
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Releases
        </Typography>
        <Button variant="contained" onClick={() => setFormOpen(true)}>
          New Release
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
          <MenuItem value="planning">Planning</MenuItem>
          <MenuItem value="in_progress">In Progress</MenuItem>
          <MenuItem value="completed">Completed</MenuItem>
          <MenuItem value="cancelled">Cancelled</MenuItem>
        </TextField>
        <TextField
          select
          label="Type"
          size="small"
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          {RELEASE_TYPES.map((t) => (
            <MenuItem key={t} value={t}>
              {t}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      <Box sx={{ height: 600, width: '100%' }}>
        <DataTable<ReleaseListItemResponse>
          storageKey="releases-list"
          userId={currentUserId}
          rows={filteredRows}
          columns={columns}
          loading={loading}
          emptyMessage="No releases yet"
          onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
        />
      </Box>

      <ReleaseForm open={formOpen} onClose={() => setFormOpen(false)} />
    </Box>
  );
}
