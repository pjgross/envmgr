/**
 * EnvironmentHealthTab — Health section for the Environment detail page.
 *
 * Shows:
 *   - Current operational status (newest sample, or "unknown" if absent/stale)
 *   - Status-history timeline (newest first): status chip + timestamp + source + detail
 *
 * Staleness rule: if the newest sample's recorded_at is older than 15 minutes,
 * the displayed current status is "unknown" (mirrors backend staleness logic).
 */
import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  Divider,
  List,
  ListItem,
  ListItemText,
  Paper,
  Typography,
} from '@mui/material';
import { environmentHealthService } from '../../services/environmentHealthService';
import type { HealthSample, HealthStatus } from '../../types/environmentHealth';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STALE_AFTER_MS = 15 * 60 * 1000; // 15 minutes

const STATUS_COLOR: Record<HealthStatus, 'success' | 'error' | 'warning' | 'default'> = {
  up: 'success',
  down: 'error',
  issue: 'warning',
  unknown: 'default',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      dateStyle: 'short',
      timeStyle: 'short',
    });
  } catch {
    return iso;
  }
}

/**
 * Derives the "current" display status from the newest sample.
 * Returns "unknown" when there are no samples or the newest is stale.
 */
function deriveCurrentStatus(samples: HealthSample[]): HealthStatus {
  if (samples.length === 0) return 'unknown';
  const newest = samples[0]; // already newest-first after sort
  const age = Date.now() - new Date(newest.recorded_at).getTime();
  if (age > STALE_AFTER_MS) return 'unknown';
  return newest.status;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  envId: number;
}

export default function EnvironmentHealthTab({ envId }: Props) {
  const [samples, setSamples] = useState<HealthSample[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setFetchError(null);
    environmentHealthService
      .history(envId)
      .then(({ rows, total: serverTotal }) => {
        // Rendered in the order the server returned. The previous re-sort by
        // recorded_at alone is now actively wrong: the query orders by
        // (recorded_at, id), so re-sorting on the timestamp can shuffle tied
        // samples into an order the paging does not share.
        setSamples(rows);
        setTotal(serverTotal);
        setFetchError(null);
      })
      .catch((err: unknown) => {
        setSamples([]);
        setTotal(0);
        setFetchError(err instanceof Error ? err.message : 'Failed to load health data');
      })
      .finally(() => {
        setLoading(false);
      });
  }, [envId]);

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (fetchError) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        {fetchError}
      </Alert>
    );
  }

  const currentStatus = deriveCurrentStatus(samples);
  const newest = samples[0] ?? null;

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Current status card */}
      <Paper sx={{ p: 3 }}>
        <Typography variant="h6" sx={{ mb: 2 }}>
          Current Status
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Chip
            label={currentStatus}
            color={STATUS_COLOR[currentStatus]}
            sx={{ textTransform: 'capitalize', fontWeight: 600 }}
          />
          {newest && (
            <Typography variant="body2" color="text.secondary">
              Last seen {formatDateTime(newest.recorded_at)} via {newest.source}
            </Typography>
          )}
          {!newest && (
            <Typography variant="body2" color="text.secondary">
              No health data reported yet.
            </Typography>
          )}
          {newest && currentStatus === 'unknown' && (
            <Typography variant="caption" color="warning.main">
              (sample is older than 15 minutes — status treated as unknown)
            </Typography>
          )}
        </Box>
      </Paper>

      {/* Status history timeline */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>
          Status History
        </Typography>
        {samples.length < total && (
          <Typography variant="caption" color="text.secondary">
            Showing the {samples.length} most recent of {total} samples.
          </Typography>
        )}
        <Divider sx={{ mb: 1.5 }} />

        {samples.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No health data reported yet.
          </Typography>
        ) : (
          <List dense disablePadding>
            {samples.map((sample) => (
              <ListItem key={sample.id} disablePadding sx={{ py: 0.5 }}>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Chip
                        label={sample.status}
                        color={STATUS_COLOR[sample.status]}
                        size="small"
                        sx={{ textTransform: 'capitalize' }}
                      />
                      <Typography variant="body2" component="span">
                        via <strong>{sample.source}</strong>
                      </Typography>
                      {sample.detail && (
                        <Typography variant="body2" color="text.secondary" component="span">
                          — {sample.detail}
                        </Typography>
                      )}
                    </Box>
                  }
                  secondary={
                    <Typography variant="caption" color="text.secondary">
                      {formatDateTime(sample.recorded_at)}
                    </Typography>
                  }
                />
              </ListItem>
            ))}
          </List>
        )}
      </Paper>
    </Box>
  );
}
