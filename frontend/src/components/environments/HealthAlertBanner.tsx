import { useEffect, useState } from 'react';
import { Alert } from '@mui/material';
import { environmentHealthService } from '../../services/environmentHealthService';

/**
 * "Who is degraded right now" — the same predicate HealthDashboard.tsx's own
 * alert banner uses (`row.alert`, computed server-side from a degraded
 * status during an active booking with no planned outage), extracted so the
 * Dashboard can reuse it UNCHANGED rather than re-deriving the rule a second
 * time. Self-contained (no props), like `ContentionHorizon`: it fetches its
 * own data and renders nothing while loading, on a failed fetch (a secondary
 * "needs attention" widget should not compete with the tiles for attention
 * over a transient error) and when nothing is alerting.
 *
 * NOTE: `HealthDashboard.tsx` was left as is rather than migrated onto this
 * component — that page also needs `rows`/`total` for its own table and
 * truncation banner, so swapping it over would mean fetching the overview
 * twice for no behavioural gain. Flagged as optional follow-on DRY cleanup,
 * not done here.
 */
export default function HealthAlertBanner() {
  const [alertingNames, setAlertingNames] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    environmentHealthService
      .overview()
      .then(({ rows }) => {
        if (cancelled) return;
        setAlertingNames(rows.filter((r) => r.alert).map((r) => r.environment_name));
      })
      .catch(() => {
        if (!cancelled) setAlertingNames([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!alertingNames || alertingNames.length === 0) return null;

  return (
    <Alert severity="error" sx={{ mb: 2 }}>
      <strong>Action required:</strong> The following environments are degraded during an active
      booking: {alertingNames.join(', ')}.
    </Alert>
  );
}
