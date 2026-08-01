/**
 * ScopeWindowsTable — releases for a system with their scope cutoff status.
 * Fetches into local state (no Redux) so it never clobbers the shared release list.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Chip, MenuItem, Stack, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { releaseService } from '../../services/releaseService';
import { useAllSystems } from '../../hooks/useAllSystems';
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

interface Props {
  /** When set, the table is fixed to this system and the system filter is hidden. */
  systemId?: number;
  /** Show the system dropdown (global page). Ignored when systemId is set. */
  showSystemFilter?: boolean;
}

export default function ScopeWindowsTable({ systemId, showSystemFilter }: Props) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ReleaseListItemResponse[]>([]);
  const [loading, setLoading] = useState(false);
  // Not the shared systems slice: since the C3 conversion (a later task) it
  // will become SystemCatalog's current filtered page, so this filter
  // dropdown would silently offer a subset.
  const { systems, truncated: systemsTruncated } = useAllSystems();
  const [selectedSystem, setSelectedSystem] = useState<number | ''>('');
  const [windowFilter, setWindowFilter] = useState<'actionable' | 'all'>('actionable');
  const [kindFilter, setKindFilter] = useState<'project' | 'enterprise' | 'all'>('project');

  const effectiveSystemId = systemId ?? (selectedSystem === '' ? undefined : Number(selectedSystem));

  useEffect(() => {
    setLoading(true);
    releaseService
      .list({
        release_kind: kindFilter === 'all' ? undefined : kindFilter,
        system_id: effectiveSystemId,
        limit: 200,
      })
      .then((paged) => setRows(paged.rows))
      .catch(() => setRows([]))
      .finally(() => setLoading(false));
  }, [effectiveSystemId, kindFilter]);

  const visibleRows = useMemo(() => {
    const filtered =
      windowFilter === 'actionable'
        ? rows.filter((r) => r.window_status === 'open' || r.window_status === 'closing_soon')
        : rows;
    // Soonest cutoff first; nulls (shipped / no_cutoff) last.
    return [...filtered].sort((a, b) => {
      const av = a.days_to_cutoff;
      const bv = b.days_to_cutoff;
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      return av - bv;
    });
  }, [rows, windowFilter]);

  const columns = useMemo<GridColDef<ReleaseListItemResponse>[]>(
    () => [
      { field: 'name', headerName: 'Release', flex: 1, minWidth: 180 },
      {
        field: 'systems',
        headerName: 'Systems',
        width: 200,
        sortable: false,
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
        renderCell: (params) => (
          <Chip
            size="small"
            label={WINDOW_LABELS[params.row.window_status] ?? params.row.window_status}
            color={WINDOW_COLORS[params.row.window_status] ?? 'default'}
          />
        ),
      },
      {
        field: 'days_to_cutoff',
        headerName: 'Days to cutoff',
        width: 130,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.days_to_cutoff === null ? (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ) : (
            <Typography variant="body2">{params.row.days_to_cutoff}</Typography>
          ),
      },
      { field: 'scope_count', headerName: 'Scope', width: 90, align: 'center', headerAlign: 'center' },
      {
        field: 'scope_creep_count',
        headerName: 'Creep',
        width: 90,
        align: 'center',
        headerAlign: 'center',
        renderCell: (params) =>
          params.row.scope_creep_count > 0 ? (
            <Chip label={params.row.scope_creep_count} color="warning" size="small" />
          ) : (
            <Typography variant="body2" color="text.secondary">—</Typography>
          ),
      },
    ],
    []
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 2, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
        {showSystemFilter && !systemId && (
          <TextField
            select
            label="System"
            size="small"
            value={selectedSystem}
            onChange={(e) => setSelectedSystem(e.target.value === '' ? '' : Number(e.target.value))}
            sx={{ minWidth: 220 }}
            helperText={
              systemsTruncated ? `Only the first ${systems.length} systems are shown.` : undefined
            }
          >
            <MenuItem value="">All systems</MenuItem>
            {systems.map((s) => (
              <MenuItem key={s.id} value={s.id}>{s.name}</MenuItem>
            ))}
          </TextField>
        )}
        <ToggleButtonGroup
          value={kindFilter}
          exclusive
          size="small"
          onChange={(_, v) => v && setKindFilter(v)}
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
          onChange={(_, v) => v && setWindowFilter(v)}
          aria-label="Window filter"
        >
          <ToggleButton value="actionable">Open / closing soon</ToggleButton>
          <ToggleButton value="all">All</ToggleButton>
        </ToggleButtonGroup>
      </Box>

      <Box sx={{ height: 560, width: '100%' }}>
        <DataTable<ReleaseListItemResponse>
          storageKey="scope-windows-table"
          rows={visibleRows}
          columns={columns}
          loading={loading}
          emptyMessage="No releases with scope windows"
          onRowClick={(params) => navigate(`/releases/${params.row.id}`)}
        />
      </Box>
    </Box>
  );
}
