/**
 * HealthDashboard — Environment Health overview.
 * Traffic-light status grid + alert banner for environments with active issues.
 * Local useState + direct service call; no Redux slice. Mirrors DoraDashboard pattern.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Alert, Box, Chip, CircularProgress, Typography } from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../../components/DataTable';
import { environmentHealthService } from '../../services/environmentHealthService';
import type { EnvironmentHealthOverviewRow, HealthStatus } from '../../types/environmentHealth';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_COLOR: Record<HealthStatus, 'success' | 'error' | 'warning' | 'default'> = {
  up: 'success',
  down: 'error',
  issue: 'warning',
  unknown: 'default',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function HealthDashboard() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<EnvironmentHealthOverviewRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setFetchError(null);
    environmentHealthService
      .overview()
      .then((data) => {
        setRows(data);
        setFetchError(null);
      })
      .catch((err: unknown) => {
        setRows([]);
        setFetchError(err instanceof Error ? err.message : 'Failed to load environment health data');
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  // Environments currently in alert state
  const alertingEnvs = useMemo(() => rows.filter((r) => r.alert), [rows]);

  const columns = useMemo<GridColDef<EnvironmentHealthOverviewRow>[]>(
    () => [
      {
        field: 'environment_name',
        headerName: 'Environment',
        flex: 1,
        minWidth: 160,
      },
      {
        field: 'current_status',
        headerName: 'Status',
        width: 130,
        renderCell: (params) => {
          const status = params.value as HealthStatus;
          return (
            <Chip
              label={status}
              color={STATUS_COLOR[status]}
              size="small"
              sx={{ textTransform: 'capitalize' }}
            />
          );
        },
      },
      {
        field: 'last_recorded_at',
        headerName: 'Last Seen',
        width: 160,
        valueFormatter: (params) => formatDateTime(params.value as string | null),
      },
      {
        field: 'active_booking_summary',
        headerName: 'Active Booking',
        flex: 1,
        minWidth: 160,
        valueGetter: (params) => {
          return params.row.active_booking_summary?.project_name ?? '—';
        },
        renderCell: (params) => <span>{params.value as string}</span>,
      },
      {
        field: 'planned_outage',
        headerName: 'Planned Outage',
        width: 140,
        valueFormatter: (params) => ((params.value as boolean) ? 'Yes' : '—'),
      },
      {
        field: 'alert',
        headerName: 'Alert',
        width: 100,
        renderCell: (params) => {
          if (!(params.value as boolean)) return <span>—</span>;
          return <Chip label="Alert" color="error" size="small" />;
        },
      },
    ],
    []
  );

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Environment Health
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Current operational status of all active environments. Alerts fire when an environment is
        degraded or down during an active booking with no planned outage.
      </Typography>

      {/* Fetch error */}
      {fetchError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {fetchError}
        </Alert>
      )}

      {/* Alert banner — shown only when at least one environment is in alert */}
      {!fetchError && alertingEnvs.length > 0 && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <strong>Action required:</strong> The following environments are degraded during an active
          booking:{' '}
          {alertingEnvs.map((r) => r.environment_name).join(', ')}.
        </Alert>
      )}

      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Box sx={{ height: 500, width: '100%' }}>
          <DataTable<EnvironmentHealthOverviewRow>
            storageKey="env-health-overview"
            rows={rows}
            columns={columns}
            getRowId={(row) => row.environment_id}
            emptyMessage="No environment health data found"
            onRowClick={(params) => navigate(`/environments/${params.row.environment_id}`)}
            sx={{ cursor: 'pointer' }}
          />
        </Box>
      )}
    </Box>
  );
}
