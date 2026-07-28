import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { AppDispatch, RootState } from '../../store';
import { fetchIncidents } from '../../store/incidentSlice';
import type { IncidentListRow } from '../../types/incident';
import { SEVERITY_COLOR, SEVERITIES } from '../../utils/incidentSeverity';
import { systemService } from '../../services/systemService';
import type { SystemResponse } from '../../types/system';

const INCIDENT_STATUSES = [
  'open',
  'investigating',
  'identified',
  'mitigated',
  'resolved',
  'closed',
];

export default function IncidentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, loading } = useSelector((s: RootState) => s.incident);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);

  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [systemFilter, setSystemFilter] = useState<string>('all');
  const [systems, setSystems] = useState<SystemResponse[]>([]);

  useEffect(() => {
    dispatch(fetchIncidents({}));
  }, [dispatch]);

  useEffect(() => {
    systemService.listSystems().then(setSystems).catch(() => setSystems([]));
  }, []);

  // When filters change, re-dispatch with server-side params where supported;
  // client-side filtering is also applied below for immediate UX.
  useEffect(() => {
    const params: Record<string, unknown> = {};
    if (statusFilter !== 'all') params.status = statusFilter;
    if (severityFilter !== 'all') params.severity = severityFilter;
    if (systemFilter !== 'all') params.system_id = systemFilter;
    dispatch(fetchIncidents(params));
  }, [statusFilter, severityFilter, systemFilter, dispatch]);

  const filteredRows = useMemo(
    () =>
      list.filter((r) => {
        if (statusFilter !== 'all' && r.status !== statusFilter) return false;
        if (severityFilter !== 'all' && r.severity !== severityFilter) return false;
        if (systemFilter !== 'all' && String(r.system_id) !== systemFilter) return false;
        return true;
      }),
    [list, statusFilter, severityFilter, systemFilter],
  );

  const columns = useMemo<GridColDef<IncidentListRow>[]>(
    () => [
      {
        field: 'title',
        headerName: 'Title',
        flex: 1,
        minWidth: 220,
      },
      {
        field: 'severity',
        headerName: 'Severity',
        width: 110,
        renderCell: (params) => (
          <Chip
            label={params.row.severity}
            color={SEVERITY_COLOR[params.row.severity] ?? 'default'}
            size="small"
          />
        ),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 130,
        renderCell: (params) => (
          <Chip label={params.row.status} size="small" variant="outlined" />
        ),
      },
      {
        field: 'system_name',
        headerName: 'System',
        width: 160,
        renderCell: (params) =>
          params.row.system_name ? (
            <Typography variant="body2">{params.row.system_name}</Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
      {
        field: 'environment_name',
        headerName: 'Environment',
        width: 160,
        renderCell: (params) =>
          params.row.environment_name ? (
            <Typography variant="body2">{params.row.environment_name}</Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
      {
        field: 'release_name',
        headerName: 'Causal Release',
        width: 160,
        renderCell: (params) =>
          params.row.release_name ? (
            <Typography variant="body2">{params.row.release_name}</Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
      {
        field: 'fix_release',
        headerName: 'Fix ETA',
        width: 130,
        renderCell: (params) => {
          const targetDate = params.row.fix_release?.target_date;
          return targetDate ? (
            <Typography variant="body2">
              {new Date(targetDate).toLocaleDateString()}
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          );
        },
      },
      {
        field: 'detected_at',
        headerName: 'Detected',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'resolved_at',
        headerName: 'Resolved',
        width: 130,
        renderCell: (params) =>
          params.row.resolved_at ? (
            <Typography variant="body2">
              {new Date(params.row.resolved_at).toLocaleDateString()}
            </Typography>
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
    ],
    [],
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 2 }}>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          Incidents
        </Typography>
        <Button variant="contained" onClick={() => navigate('/incidents/new')}>
          New Incident
        </Button>
      </Box>

      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <TextField
          select
          label="Status"
          size="small"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          {INCIDENT_STATUSES.map((s) => (
            <MenuItem key={s} value={s}>
              {s}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Severity"
          size="small"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          sx={{ minWidth: 130 }}
        >
          <MenuItem value="all">All</MenuItem>
          {SEVERITIES.map((s) => (
            <MenuItem key={s} value={s}>
              {s}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="System"
          size="small"
          value={systemFilter}
          onChange={(e) => setSystemFilter(e.target.value)}
          sx={{ minWidth: 180 }}
          disabled={systems.length === 0}
        >
          <MenuItem value="all">All systems</MenuItem>
          {systems.map((s) => (
            <MenuItem key={s.id} value={String(s.id)}>
              {s.name}
            </MenuItem>
          ))}
        </TextField>
      </Box>

      <Box sx={{ height: 600, width: '100%' }}>
        <DataTable<IncidentListRow>
          storageKey="incidents-list"
          userId={currentUserId}
          rows={filteredRows}
          columns={columns}
          loading={loading}
          emptyMessage="No incidents found"
          onRowClick={(params) => navigate(`/incidents/${params.row.id}`)}
        />
      </Box>
    </Box>
  );
}
