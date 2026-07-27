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
import type {
  ScopeChurnAnalyticsResponse,
  ChurnCohortResponse,
  ChurnReleaseRowResponse,
} from '../../types/release';

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
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

  useEffect(() => {
    releaseService
      .getScopeChurnAnalytics({
        date_from: from ? new Date(`${from}T00:00:00Z`).toISOString() : undefined,
        date_to: to ? new Date(`${to}T23:59:59Z`).toISOString() : undefined,
      })
      .then(setData)
      .catch(() => setData(null));
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
