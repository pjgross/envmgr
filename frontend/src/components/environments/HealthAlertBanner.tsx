import { useEffect, useState } from 'react';
import { Alert } from '@mui/material';
import { environmentHealthService } from '../../services/environmentHealthService';

/**
 * "Who is degraded right now" — the same predicate `HealthDashboard.tsx`'s
 * own alert banner uses (`row.alert`, computed server-side from a degraded
 * status during an active booking with no planned outage). `HealthDashboard`
 * (`frontend/src/pages/insights/HealthDashboard.tsx`) HAS BEEN migrated onto
 * this shared component (see its own render), so the Dashboard reuses it
 * UNCHANGED rather than re-deriving the rule a second time. Self-contained
 * (no props), like `ContentionHorizon`: it fetches its own data and renders
 * nothing while loading or when nothing is alerting.
 *
 * A FAILED FETCH IS NEVER SILENCE (finding 3 of the PR 3 whole-branch
 * review). The old `catch(() => setAlertingNames([]))` rendered exactly what
 * "everything is healthy" renders — null — so a request failure and a clean
 * bill of health were indistinguishable to the reader. `failed` now renders
 * its own warning instead.
 */
export default function HealthAlertBanner() {
  const [alertingNames, setAlertingNames] = useState<string[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    environmentHealthService
      .overview()
      .then(({ rows }) => {
        if (cancelled) return;
        setAlertingNames(rows.filter((r) => r.alert).map((r) => r.environment_name));
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <Alert severity="warning" sx={{ mb: 2 }}>
        Couldn&apos;t check environment health right now.
      </Alert>
    );
  }

  if (!alertingNames || alertingNames.length === 0) return null;

  return (
    <Alert severity="error" sx={{ mb: 2 }}>
      <strong>Action required:</strong> The following environments are degraded during an active
      booking: {alertingNames.join(', ')}.
    </Alert>
  );
}
