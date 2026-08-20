/**
 * ReadinessBanner — Phase 9 C2's gate readiness verdict, rendered at the top
 * of the release detail page.
 *
 * C2 ADVISES; IT NEVER BLOCKS. `GET /releases/{id}/readiness` calls the same
 * `gate_readiness_service.evaluate` a deployment pipeline may choose to obey
 * via `GET /webhooks/release-ready` — but nothing in THIS app refuses a
 * release transition, a deployment or a booking on the strength of it (see
 * backend/tests/test_c2_advises_never_blocks.py). This banner is read-only:
 * it renders every blocker and warning it is given, and disables nothing.
 * Do not wire its presence into TransitionControls or any other control —
 * that would turn an advisory verdict into an enforced one.
 */
import { useEffect, useState } from 'react';
import { Alert, Box, Typography } from '@mui/material';
import { releaseService } from '../../services/releaseService';
import type { ReleaseReadinessResponse } from '../../types/gateReadiness';

interface Props {
  releaseId: number;
}

const describeItem = (gateName: string, gateType: string | null, detail: string | null): string => {
  const typed = gateType ? `${gateName} (${gateType})` : gateName;
  return detail ? `${typed} — ${detail}` : typed;
};

export default function ReadinessBanner({ releaseId }: Props) {
  const [readiness, setReadiness] = useState<ReleaseReadinessResponse | null>(null);

  useEffect(() => {
    if (!releaseId) return;
    let cancelled = false;
    releaseService
      .getReadiness(releaseId)
      .then((r) => {
        if (!cancelled) setReadiness(r);
      })
      .catch(() => {
        // A failed readiness check must not block rendering the rest of the
        // page — the banner simply has nothing to say.
        if (!cancelled) setReadiness(null);
      });
    return () => {
      cancelled = true;
    };
  }, [releaseId]);

  if (!readiness) return null;
  const { blockers, warnings } = readiness;
  if (blockers.length === 0 && warnings.length === 0) return null;

  return (
    <Alert severity={blockers.length > 0 ? 'warning' : 'info'} sx={{ mb: 2 }}>
      <Typography variant="body2" fontWeight="medium">
        Readiness check — advisory only. Nothing here blocks this release's
        transitions, deployments or bookings; a connected deployment pipeline
        may choose to act on it.
      </Typography>

      {blockers.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="body2" fontWeight="medium">
            {blockers.length} in the verdict:
          </Typography>
          <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2 }}>
            {blockers.map((b) => (
              <li key={`${b.ref_kind}-${b.ref_id}-${b.type}`}>
                <Typography variant="body2">
                  {describeItem(b.gate_name, b.gate_type, b.detail)}
                </Typography>
              </li>
            ))}
          </Box>
        </Box>
      )}

      {warnings.length > 0 && (
        <Box sx={{ mt: 1 }}>
          <Typography variant="body2" fontWeight="medium">
            {warnings.length} advisory:
          </Typography>
          <Box component="ul" sx={{ mt: 0.5, mb: 0, pl: 2 }}>
            {warnings.map((w) => (
              <li key={`${w.ref_kind}-${w.ref_id}-${w.type}`}>
                <Typography variant="body2">
                  {describeItem(w.gate_name, w.gate_type, w.detail)}
                </Typography>
              </li>
            ))}
          </Box>
        </Box>
      )}
    </Alert>
  );
}
