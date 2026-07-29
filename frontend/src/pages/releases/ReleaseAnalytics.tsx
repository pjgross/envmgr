/**
 * ReleaseAnalytics — does changing a release's scope correlate with delays/issues?
 * Descriptive correlation over shipped project releases in a date window.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Box, Card, CardContent, Chip, TextField, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { releaseService } from '../../services/releaseService';
import { releaseMetricsService } from '../../services/releaseMetricsService';
import type { ReleaseMetrics, BookingConflictRow } from '../../types/releaseMetrics';
import type {
  ScopeChurnAnalyticsResponse,
  ChurnCohortResponse,
  ChurnReleaseRowResponse,
} from '../../types/release';

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatDuration(seconds: number): string {
  if (seconds <= 0) return '0m';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0 || parts.length === 0) parts.push(`${minutes}m`);
  return parts.join(' ');
}

function MetricCard({ title, primary, secondary }: { title: string; primary: string; secondary: string }) {
  return (
    <Card variant="outlined" sx={{ flex: 1, minWidth: 220 }}>
      <CardContent>
        <Typography variant="subtitle2" color="text.secondary" gutterBottom>{title}</Typography>
        <Typography variant="h4" sx={{ mt: 0.5, fontWeight: 'bold' }}>{primary}</Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{secondary}</Typography>
      </CardContent>
    </Card>
  );
}

function CohortCard({ title, cohort }: { title: string; cohort: ChurnCohortResponse }) {
  return (
    <Card variant="outlined" sx={{ flex: 1, minWidth: 240 }}>
      <CardContent>
        <Typography variant="subtitle1" fontWeight="medium">
          {title} ({cohort.count})
        </Typography>
        <Typography variant="h4" sx={{ mt: 1 }}>{cohort.delayed_pct}%</Typography>
        <Typography variant="body2" color="text.secondary">
          delayed ({cohort.delayed_count}/{cohort.count})
        </Typography>
        <Typography variant="h4" sx={{ mt: 1 }}>{cohort.issue_pct}%</Typography>
        <Typography variant="body2" color="text.secondary">
          had an issue ({cohort.issue_count}/{cohort.count})
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function ReleaseAnalytics() {
  const navigate = useNavigate();
  const [from, setFrom] = useState(() => isoDate(new Date(Date.now() - 90 * 864e5)));
  const [to, setTo] = useState(() => isoDate(new Date()));
  const [data, setData] = useState<ScopeChurnAnalyticsResponse | null>(null);
  const [metrics, setMetrics] = useState<ReleaseMetrics | null>(null);
  const [conflicts, setConflicts] = useState<BookingConflictRow[]>([]);

  useEffect(() => {
    releaseService
      .getScopeChurnAnalytics({
        date_from: from ? new Date(`${from}T00:00:00Z`).toISOString() : undefined,
        date_to: to ? new Date(`${to}T23:59:59Z`).toISOString() : undefined,
      })
      .then(setData)
      .catch(() => setData(null));
  }, [from, to]);

  useEffect(() => {
    if (!from || !to) return;
    const params = { date_from: from, date_to: to };
    releaseMetricsService.releases(params).then(setMetrics).catch(() => setMetrics(null));
    releaseMetricsService.conflicts(params).then(setConflicts).catch(() => setConflicts([]));
  }, [from, to]);

  const columns = useMemo<GridColDef<ChurnReleaseRowResponse>[]>(
    () => [
      { field: 'name', headerName: 'Release', flex: 1, minWidth: 180 },
      {
        field: 'shipped_at',
        headerName: 'Shipped',
        width: 130,
        valueFormatter: (params) =>
          params.value ? new Date(params.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'scope_changed',
        headerName: 'Scope changed',
        width: 140,
        renderCell: (params) =>
          params.row.scope_changed ? <Chip label="Yes" color="warning" size="small" /> : <span>—</span>,
      },
      {
        field: 'delayed',
        headerName: 'Delayed',
        width: 110,
        renderCell: (params) =>
          params.row.delayed ? <Chip label="Yes" color="error" size="small" /> : <span>—</span>,
      },
      {
        field: 'had_issue',
        headerName: 'Issue',
        width: 110,
        renderCell: (params) =>
          params.row.had_issue ? <Chip label="Yes" color="error" size="small" /> : <span>—</span>,
      },
    ],
    []
  );

  const conflictColumns = useMemo<GridColDef<BookingConflictRow>[]>(
    () => [
      { field: 'environment_name', headerName: 'Environment', flex: 1, minWidth: 180 },
      { field: 'month', headerName: 'Month', width: 120 },
      { field: 'conflict_count', headerName: 'Conflicting pairs', width: 150, type: 'number' },
    ],
    []
  );

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>Release Analytics</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Descriptive correlation between scope change and delays / issues across shipped project
        releases in the selected window — not a causal claim.
      </Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
        <TextField label="From" type="date" size="small" value={from}
          onChange={(e) => setFrom(e.target.value)} InputLabelProps={{ shrink: true }} />
        <TextField label="To" type="date" size="small" value={to}
          onChange={(e) => setTo(e.target.value)} InputLabelProps={{ shrink: true }} />
      </Box>

      {metrics && (
        <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
          <MetricCard
            title="Release Success Rate"
            primary={metrics.shipped_count === 0 ? 'No data' : `${(metrics.success_rate * 100).toFixed(1)}%`}
            secondary={metrics.shipped_count === 0
              ? 'No shipped releases in range'
              : `${metrics.shipped_count - metrics.failed_count} of ${metrics.shipped_count} shipped OK`}
          />
          <MetricCard
            title="Emergency Releases"
            primary={metrics.closed_count === 0 ? 'No data' : `${(metrics.emergency_pct * 100).toFixed(1)}%`}
            secondary={metrics.closed_count === 0
              ? 'No closed releases in range'
              : `${metrics.emergency_count} of ${metrics.closed_count} closed`}
          />
          <MetricCard
            title="Avg Cycle Time"
            primary={metrics.cycle_time_count === 0 ? 'No data' : formatDuration(metrics.avg_cycle_time_seconds)}
            secondary={metrics.cycle_time_count === 0
              ? 'No shipped releases with a ship date'
              : `created → shipped, ${metrics.cycle_time_count} release${metrics.cycle_time_count !== 1 ? 's' : ''}`}
          />
        </Box>
      )}

      <Typography variant="subtitle1" sx={{ mb: 1 }}>Booking Conflicts (by environment / month)</Typography>
      <Box sx={{ height: 300, width: '100%', mb: 3 }}>
        <DataTable<BookingConflictRow>
          storageKey="release-analytics-conflicts"
          rows={conflicts}
          columns={conflictColumns}
          emptyMessage="No booking conflicts in range"
          getRowId={(row) => `${row.environment_id}-${row.month}`}
        />
      </Box>

      {data && (
        <>
          <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
            <CohortCard title="Scope changed" cohort={data.scope_changed} />
            <CohortCard title="Stable scope" cohort={data.stable} />
          </Box>

          <Box sx={{ height: 480, width: '100%' }}>
            <DataTable<ChurnReleaseRowResponse>
              storageKey="release-analytics"
              rows={data.releases}
              columns={columns}
              emptyMessage="No shipped releases in this window"
              getRowId={(row) => row.release_id}
              onRowClick={(params) => navigate(`/releases/${params.row.release_id}`)}
            />
          </Box>
        </>
      )}
    </Box>
  );
}
