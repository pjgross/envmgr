import { useEffect, useState } from "react";
import { Paper, Stack, Typography, Chip, Alert } from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { enterpriseMembershipService } from "../../../services/enterpriseMembershipService";
import type { ReleaseMembership } from "../../../types/enterpriseMembership";

interface Props {
  releaseId: number;
}

export function EnterpriseMembershipTab({ releaseId }: Props) {
  const [current, setCurrent] = useState<ReleaseMembership | null>(null);
  const [history, setHistory] = useState<ReleaseMembership[]>([]);

  useEffect(() => {
    if (releaseId == null) return;
    enterpriseMembershipService.getProjectMembership(releaseId).then((r) => {
      setCurrent(r.current);
      setHistory(r.history);
    });
  }, [releaseId]);

  return (
    <Stack spacing={3}>
      {current ? (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1">
            Part of enterprise release:{" "}
            <RouterLink to={`/releases/${current.enterpriseReleaseId}`}>
              {current.enterpriseReleaseName ?? `Release #${current.enterpriseReleaseId}`}
            </RouterLink>
          </Typography>
          <Typography variant="body2">
            Admitted {current.decidedAt ? new Date(current.decidedAt).toLocaleString() : "—"}
            {" "}by {current.decidedByUsername ?? "—"}
          </Typography>
          {current.lateScope && (
            <Chip color="warning" size="small" label="Late scope" sx={{ mt: 1 }} />
          )}
        </Paper>
      ) : (
        <Alert severity="info">This release is not part of any enterprise release.</Alert>
      )}

      <Typography variant="h6">History</Typography>
      <Paper sx={{ p: 2 }}>
        {history.length === 0 ? (
          <Typography variant="body2">No previous membership requests.</Typography>
        ) : (
          <ul>
            {history.map((h) => (
              <li key={h.id}>
                {h.state} · {h.enterpriseReleaseName ?? `enterprise #${h.enterpriseReleaseId}`} ·{" "}
                {new Date(h.requestedAt).toLocaleString()}
                {h.removalReason ? ` — ${h.removalReason}` : ""}
                {h.notes ? ` (${h.notes})` : ""}
              </li>
            ))}
          </ul>
        )}
      </Paper>
    </Stack>
  );
}
