import { useEffect, useMemo } from 'react';
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
import ComputedColumnHeader from '../../components/ComputedColumnHeader';
import { AppDispatch, RootState } from '../../store';
import { fetchIncidents } from '../../store/incidentSlice';
import {
  fetchLifecycleTemplates,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { useServerGrid } from '../../hooks/useServerGrid';
import type { IncidentListRow } from '../../types/incident';
import { SEVERITY_COLOR, SEVERITIES } from '../../utils/incidentSeverity';
import { useAllSystems } from '../../hooks/useAllSystems';
import PageHeader from '../../components/layout/PageHeader';

// Sortable fields (whitelist-backed, see frontend/src/constants/sortWhitelists.json
// "incidents"): title, severity, status, detected_at, resolved_at. system_name,
// environment_name and release_name are joins the endpoint doesn't whitelist for
// sorting; fix_release and pir_status are computed after the page is fetched —
// none is backed by a single column the database could order by, so none ever
// was or can be sortable.
// A plain array export, not a component; co-located here per the C3 pilot's
// releaseColumns precedent (small enough not to warrant its own file).
// eslint-disable-next-line react-refresh/only-export-components
export const incidentColumns: GridColDef<IncidentListRow>[] = [
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
    sortable: false,
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
    sortable: false,
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
    sortable: false,
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
    sortable: false,
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
  {
    field: 'pir_status',
    headerName: 'Reviewed',
    width: 130,
    sortable: false,
    renderHeader: () => <ComputedColumnHeader label="Reviewed" />,
    renderCell: (params) => {
      const s = params.row.pir_status;
      if (s === 'complete') return <Chip label="Complete" color="success" size="small" />;
      if (s === 'draft') return <Chip label="Draft" color="warning" size="small" />;
      return <Typography variant="body2" color="text.secondary">—</Typography>;
    },
  },
];

export default function IncidentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { list, total, listLoading } = useSelector((s: RootState) => s.incident);
  const currentUserId = useSelector((s: RootState) => s.auth.user?.id);
  const incidentTemplates = useSelector(selectTemplatesForEntity('incident'));

  // Not the shared systems slice: since the C3 conversion (a later task) it
  // will become SystemCatalog's current filtered page, so this filter
  // dropdown would silently offer a subset.
  const { systems, truncated: systemsTruncated } = useAllSystems();

  const grid = useServerGrid({
    endpoint: 'incidents',
    // `open` has no filter UI on this page — it exists so the Dashboard's
    // "Open incidents" tile can link here with `?open=true` already in the
    // URL and land on the SAME rows it counted. Without this in filterKeys,
    // useServerGrid never reads it out of the URL, `fetchIncidents` never
    // gets it, and the tile and the page it links to would silently
    // disagree — the same failure BookingList's `start`/`end` entries guard.
    filterKeys: ['status', 'severity', 'system_id', 'open'],
    onFetch: (params) => dispatch(fetchIncidents(params)),
    total,
    totalPending: listLoading,
  });

  // Status options come from the tenant's default incident lifecycle
  // template, not from `list` — `list` is now one server-paged/filtered/sorted
  // window, and deriving options from it would only offer statuses present on
  // the currently loaded page, making some statuses unreachable via the filter.
  const statusOptions = useMemo(() => {
    const defaultTpl = incidentTemplates.find((t) => t.is_default) ?? incidentTemplates[0] ?? null;
    return defaultTpl?.definition?.states?.length
      ? defaultTpl.definition.states.map((s) => ({ key: s.key, label: s.label }))
      : [];
  }, [incidentTemplates]);

  useEffect(() => {
    dispatch(fetchLifecycleTemplates('incident'));
  }, [dispatch]);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Incidents"
        actions={
          <Button variant="contained" onClick={() => navigate('/incidents/new')}>
            New Incident
          </Button>
        }
      />

      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        <TextField
          select
          label="Status"
          size="small"
          value={grid.filters.status ?? 'all'}
          onChange={(e) => grid.setFilter('status', e.target.value)}
          sx={{ minWidth: 160 }}
        >
          <MenuItem value="all">All</MenuItem>
          {statusOptions.map((s) => (
            <MenuItem key={s.key} value={s.key}>
              {s.label}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          label="Severity"
          size="small"
          value={grid.filters.severity ?? 'all'}
          onChange={(e) => grid.setFilter('severity', e.target.value)}
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
          value={grid.filters.system_id ?? 'all'}
          onChange={(e) => grid.setFilter('system_id', e.target.value)}
          sx={{ minWidth: 180 }}
          disabled={systems.length === 0}
          helperText={
            systemsTruncated ? `Only the first ${systems.length} systems are shown.` : undefined
          }
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
          rows={list}
          columns={incidentColumns}
          loading={listLoading}
          rowCount={total}
          paginationMode="server"
          sortingMode="server"
          paginationModel={grid.paginationModel}
          onPaginationModelChange={grid.onPaginationModelChange}
          sortModel={grid.sortModel}
          onSortModelChange={grid.onSortModelChange}
          pageSizeOptions={[10, 25, 50, 100]}
          emptyMessage="No incidents found"
          onRowClick={(params) => navigate(`/incidents/${params.row.id}`)}
        />
      </Box>
    </Box>
  );
}
