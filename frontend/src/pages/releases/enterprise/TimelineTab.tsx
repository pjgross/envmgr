import { useEffect, useState } from "react";
import {
  Paper, Stack, Typography, Divider, List, ListItem, ListItemText, Chip,
} from "@mui/material";
import { enterpriseRollupService } from "../../../services/enterpriseRollupService";
import type { TimelineRollup, TimelinePhase } from "../../../types/enterpriseReport";
import type { ReleaseResponse } from "../../../types/release";

interface Props {
  release: ReleaseResponse;
}

function PhaseListItem({ phase }: { phase: TimelinePhase }) {
  const fmt = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleDateString() : "";
  const range = phase.startDate || phase.endDate
    ? `${fmt(phase.startDate)} — ${fmt(phase.endDate)}`
    : "";
  return (
    <ListItem dense>
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center">
            <strong>{phase.phaseName}</strong>
            {phase.status && <Chip label={phase.status} size="small" />}
          </Stack>
        }
        secondary={range}
      />
    </ListItem>
  );
}

export function TimelineTab({ release }: Props) {
  const [data, setData] = useState<TimelineRollup | null>(null);

  useEffect(() => {
    if (release?.id == null) return;
    enterpriseRollupService.timeline(release.id).then(setData);
  }, [release?.id]);

  if (!data) return <Paper sx={{ p: 2 }}><Typography>Loading timeline…</Typography></Paper>;

  const childEntries = Object.entries(data.childPhasesByRelease);

  return (
    <Stack spacing={3}>
      <Paper sx={{ p: 2 }}>
        <Typography variant="h6" gutterBottom>{release.name} — enterprise phases</Typography>
        {data.enterprisePhases.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No enterprise-level phases defined.</Typography>
        ) : (
          <List dense>
            {data.enterprisePhases.map((p, i) => (
              <PhaseListItem key={p.phaseId ?? i} phase={p} />
            ))}
          </List>
        )}
      </Paper>

      {childEntries.map(([rid, phases]) => (
        <Paper key={rid} sx={{ p: 2 }}>
          <Typography variant="subtitle1" gutterBottom>
            {phases[0]?.releaseName ?? `Release ${rid}`}
          </Typography>
          {phases.length === 0 ? (
            <Typography variant="body2" color="text.secondary">No phases defined.</Typography>
          ) : (
            <List dense>
              {phases.map((p, i) => <PhaseListItem key={p.phaseId ?? i} phase={p} />)}
            </List>
          )}
        </Paper>
      ))}

      {data.dependencies.length > 0 && (
        <Paper sx={{ p: 2 }}>
          <Typography variant="subtitle1" gutterBottom>Dependencies</Typography>
          <Divider />
          <List dense>
            {data.dependencies.map((d) => (
              <ListItem key={`${d.fromReleaseId}-${d.toReleaseId}`} dense>
                <ListItemText primary={
                  `${d.fromReleaseName ?? `Release #${d.fromReleaseId}`} → ${d.toReleaseName ?? `Release #${d.toReleaseId}`}${d.alert ? ` (${d.alert})` : ""}`
                } />
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
    </Stack>
  );
}
