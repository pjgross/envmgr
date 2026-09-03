/**
 * DoraDashboard — DORA metrics (Deployment Frequency, Lead Time, Change Failure Rate, MTTR).
 * Local useState + direct service call; no Redux slice. Mirrors ReleaseAnalytics pattern.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  TextField,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { doraService } from '../../services/doraService';
import { environmentService } from '../../services/environmentService';
import { releaseService } from '../../services/releaseService';
import type { DoraSummary, DoraParams } from '../../types/dora';
import type { EnvironmentResponse } from '../../types/environment';
import type { ReleaseListItemResponse } from '../../types/release';
import api from '../../services/api';
import PageHeader from '../../components/layout/PageHeader';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Trend table row type
// ---------------------------------------------------------------------------

interface TrendRow {
  period: string;
  deployments: number;
  lead_time_median_seconds: number;
  mttr_mean_seconds: number;
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

function StatCard({
  title,
  primary,
  secondary,
}: {
  title: string;
  primary: string;
  secondary: string;
}) {
  return (
    <Card variant="outlined" sx={{ flex: 1, minWidth: 220 }}>
      <CardContent>
        <Typography variant="subtitle2" color="text.secondary" gutterBottom>
          {title}
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5, fontWeight: 'bold' }}>
          {primary}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {secondary}
        </Typography>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DoraDashboard() {
  const [from, setFrom] = useState(() => isoDate(new Date(Date.now() - 90 * 864e5)));
  const [to, setTo] = useState(() => isoDate(new Date()));
  const [environmentId, setEnvironmentId] = useState<number | undefined>(undefined);
  const [releaseOption, setReleaseOption] = useState<ReleaseListItemResponse | null>(null);
  const [granularity, setGranularity] = useState<'day' | 'week' | 'month'>('week');

  const [data, setData] = useState<DoraSummary | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [exportError, setExportError] = useState(false);
  const [environments, setEnvironments] = useState<EnvironmentResponse[]>([]);
  const [releases, setReleases] = useState<ReleaseListItemResponse[]>([]);

  // Load filter options once
  useEffect(() => {
    environmentService
      .listEnvironments()
      .then((paged) => setEnvironments(paged.rows))
      .catch(() => setEnvironments([]));
    // Explicit limit: the server default is 50, which silently omits releases
    // from a picker with no indication any are missing.
    releaseService.list({ limit: 200 }).then((paged) => setReleases(paged.rows)).catch(() => setReleases([]));
  }, []);

  // Fetch DORA summary whenever filters change
  useEffect(() => {
    const params: DoraParams = {
      date_from: from,
      date_to: to,
      granularity,
    };
    if (environmentId !== undefined) params.environment_id = environmentId;
    if (releaseOption) params.release_id = releaseOption.id;

    setFetchError(null);
    doraService
      .getSummary(params)
      .then((d) => { setData(d); setFetchError(null); })
      .catch((err: unknown) => {
        setData(null);
        const msg = err instanceof Error ? err.message : 'Failed to load DORA metrics';
        setFetchError(msg);
      });
  }, [from, to, environmentId, releaseOption, granularity]);

  // Build current params for export
  const currentParams = useMemo((): DoraParams => {
    const p: DoraParams = {
      date_from: from,
      date_to: to,
      granularity,
    };
    if (environmentId !== undefined) p.environment_id = environmentId;
    if (releaseOption) p.release_id = releaseOption.id;
    return p;
  }, [from, to, environmentId, releaseOption, granularity]);

  // CSV export through authenticated axios client (bearer JWT — window.open would 401)
  const handleExport = async () => {
    try {
      const res = await api.get('/metrics/dora/export', {
        params: currentParams,
        responseType: 'blob',
      });
      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'dora-metrics.csv';
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setExportError(true);
    }
  };

  // Merge series by period for the trend table
  const trendRows = useMemo<TrendRow[]>(() => {
    if (!data) return [];
    const map = new Map<string, TrendRow>();

    for (const p of data.deployment_frequency.series) {
      map.set(p.period, {
        period: p.period,
        deployments: p.count,
        lead_time_median_seconds: 0,
        mttr_mean_seconds: 0,
      });
    }
    for (const p of data.lead_time.series) {
      const row = map.get(p.period);
      if (row) {
        row.lead_time_median_seconds = p.median_seconds;
      } else {
        map.set(p.period, {
          period: p.period,
          deployments: 0,
          lead_time_median_seconds: p.median_seconds,
          mttr_mean_seconds: 0,
        });
      }
    }
    for (const p of data.mttr.series) {
      const row = map.get(p.period);
      if (row) {
        row.mttr_mean_seconds = p.mean_seconds;
      } else {
        map.set(p.period, {
          period: p.period,
          deployments: 0,
          lead_time_median_seconds: 0,
          mttr_mean_seconds: p.mean_seconds,
        });
      }
    }

    return Array.from(map.values()).sort((a, b) => a.period.localeCompare(b.period));
  }, [data]);

  const trendColumns = useMemo<GridColDef<TrendRow>[]>(
    () => [
      { field: 'period', headerName: 'Period', flex: 1, minWidth: 120 },
      { field: 'deployments', headerName: 'Deployments', width: 140, type: 'number' },
      {
        field: 'lead_time_median_seconds',
        headerName: 'Lead Time (median)',
        width: 180,
        valueFormatter: (params) => formatDuration(params.value as number),
      },
      {
        field: 'mttr_mean_seconds',
        headerName: 'MTTR (mean)',
        width: 160,
        valueFormatter: (params) => formatDuration(params.value as number),
      },
    ],
    []
  );

  // Derived card values
  const df = data?.deployment_frequency;
  const lt = data?.lead_time;
  const cfr = data?.change_failure_rate;
  const mttr = data?.mttr;

  const periodCount = trendRows.length || 1;
  const avgPerPeriod = df ? (df.total / periodCount).toFixed(1) : '—';

  const cfrPrimary =
    cfr === undefined
      ? '—'
      : cfr.shipped_count === 0
      ? 'No data'
      : `${(cfr.rate * 100).toFixed(1)}%`;
  const cfrSecondary =
    cfr === undefined
      ? ''
      : cfr.shipped_count === 0
      ? 'No shipped changes in range'
      : `${cfr.failed_count} failed / ${cfr.shipped_count} shipped`;

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="DORA Metrics"
        subtitle="Deployment Frequency, Lead Time for Changes, Change Failure Rate, and Mean Time to Restore over the selected window."
      />

      {/* Filter bar */}
      <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <TextField
          label="From"
          type="date"
          size="small"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          InputLabelProps={{ shrink: true }}
        />
        <TextField
          label="To"
          type="date"
          size="small"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          InputLabelProps={{ shrink: true }}
        />

        <FormControl size="small" sx={{ minWidth: 180 }}>
          <InputLabel id="env-label">Environment</InputLabel>
          <Select
            labelId="env-label"
            label="Environment"
            value={environmentId === undefined ? '' : String(environmentId)}
            onChange={(e: SelectChangeEvent) => {
              const v = e.target.value;
              setEnvironmentId(v === '' ? undefined : Number(v));
            }}
          >
            <MenuItem value="">All</MenuItem>
            {environments.map((env) => (
              <MenuItem key={env.id} value={String(env.id)}>
                {env.name}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Autocomplete<ReleaseListItemResponse>
          size="small"
          sx={{ minWidth: 220 }}
          options={releases}
          getOptionLabel={(r) => r.name}
          value={releaseOption}
          onChange={(_, val) => setReleaseOption(val)}
          renderInput={(params) => <TextField {...params} label="Release (optional)" />}
        />

        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel id="gran-label">Granularity</InputLabel>
          <Select
            labelId="gran-label"
            label="Granularity"
            value={granularity}
            onChange={(e: SelectChangeEvent) =>
              setGranularity(e.target.value as 'day' | 'week' | 'month')
            }
          >
            <MenuItem value="day">Day</MenuItem>
            <MenuItem value="week">Week</MenuItem>
            <MenuItem value="month">Month</MenuItem>
          </Select>
        </FormControl>

        <Button variant="outlined" size="small" onClick={handleExport}>
          Export CSV
        </Button>
      </Box>

      {fetchError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {fetchError}
        </Alert>
      )}

      <Snackbar
        open={exportError}
        autoHideDuration={4000}
        onClose={() => setExportError(false)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity="error" onClose={() => setExportError(false)}>
          CSV export failed. Please try again.
        </Alert>
      </Snackbar>

      {data && (
        <>
          {/* Stat cards */}
          <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
            <StatCard
              title="Deployment Frequency"
              primary={df ? String(df.total) : '—'}
              secondary={`${avgPerPeriod} per ${granularity}`}
            />
            <StatCard
              title="Lead Time for Changes"
              primary={lt ? formatDuration(lt.median_seconds) : '—'}
              secondary={lt ? `p90: ${formatDuration(lt.p90_seconds)}` : ''}
            />
            <StatCard
              title="Change Failure Rate"
              primary={cfrPrimary}
              secondary={cfrSecondary}
            />
            <StatCard
              title="Mean Time to Restore"
              primary={mttr ? formatDuration(mttr.mean_seconds) : '—'}
              secondary={mttr ? `${mttr.count} incident${mttr.count !== 1 ? 's' : ''} resolved` : ''}
            />
          </Box>

          {/* Trend table */}
          <Box sx={{ height: 400, width: '100%' }}>
            <DataTable<TrendRow>
              storageKey="dora-trend"
              rows={trendRows}
              columns={trendColumns}
              emptyMessage="No data in this window"
              getRowId={(row) => row.period}
            />
          </Box>
        </>
      )}
    </Box>
  );
}
