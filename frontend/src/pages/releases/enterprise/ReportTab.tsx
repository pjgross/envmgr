import { useEffect, useState } from "react";
import {
  Button, Paper, Stack, Typography, Divider, Chip,
} from "@mui/material";
import { enterpriseReportService } from "../../../services/enterpriseReportService";
import type { EnterpriseReport } from "../../../types/enterpriseReport";
import type { ReleaseResponse } from "../../../types/release";

interface Props {
  release: ReleaseResponse;
}

export function ReportTab({ release }: Props) {
  const [report, setReport] = useState<EnterpriseReport | null>(null);

  useEffect(() => {
    if (release?.id == null) return;
    enterpriseReportService.generate(release.id).then(setReport);
  }, [release?.id]);

  if (!report) return <Paper sx={{ p: 2 }}><Typography>Generating report…</Typography></Paper>;

  return (
    <Stack spacing={3} className="enterprise-report">
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <div>
          <Typography variant="h4">{report.name}</Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
            <Chip label={report.status} size="small" />
            {report.targetDate && (
              <Typography variant="body2">
                Target: {new Date(report.targetDate).toLocaleDateString()}
              </Typography>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary">
            Generated {new Date(report.generatedAt).toLocaleString()} by {report.generatedBy}
          </Typography>
        </div>
        <Button variant="outlined" onClick={() => window.print()}>Print</Button>
      </Stack>

      <Divider />

      <section>
        <Typography variant="h5" gutterBottom>Member projects</Typography>
        {report.members.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No member projects.</Typography>
        ) : (
          <ul>
            {report.members.map((m) => (
              <li key={m.projectReleaseId}>
                <strong>{m.projectReleaseName}</strong> — {m.status}
                {m.lateScope && (
                  <Chip label="late scope" color="warning" size="small" sx={{ ml: 1 }} />
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <Typography variant="h5" gutterBottom>Systems impacted</Typography>
        {report.systems.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No systems recorded on accepted members.</Typography>
        ) : (
          <ul>
            {report.systems.map((s) => (
              <li key={s.systemId}>
                <strong>{s.systemName}</strong>
                <ul>
                  {Object.entries(s.rolesByProject).map(([proj, roles]) => (
                    <li key={proj}>{proj}: {roles.join(", ")}</li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <Typography variant="h5" gutterBottom>Jira tickets delivered</Typography>
        {Object.keys(report.scopeByProject).length === 0 ? (
          <Typography variant="body2" color="text.secondary">No scope recorded on accepted members.</Typography>
        ) : (
          Object.entries(report.scopeByProject).map(([proj, items]) => (
            <Paper key={proj} sx={{ p: 2, mb: 1 }} variant="outlined">
              <Typography variant="subtitle1">{proj}</Typography>
              <ul>
                {items.map((it) => (
                  <li key={it.releaseChangeId}>
                    <strong>{it.externalKey ?? "—"}</strong> · {it.title} ({it.changeKind})
                    {it.externalStatus ? ` · ${it.externalStatus}` : ""}
                  </li>
                ))}
              </ul>
            </Paper>
          ))
        )}
      </section>

      {report.events.length > 0 && (
        <section>
          <Typography variant="h5" gutterBottom>Notable events</Typography>
          <ul>
            {report.events.slice(0, 30).map((e, i) => (
              <li key={i}>
                {new Date(e.occurredAt).toLocaleString()} · {e.releaseName} · {e.eventType}
                {e.description ? ` — ${e.description}` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}

      {report.dependencies.length > 0 && (
        <section>
          <Typography variant="h5" gutterBottom>Dependencies</Typography>
          <ul>
            {report.dependencies.map((d, i) => (
              <li key={i}>
                Release #{d.fromReleaseId} → Release #{d.toReleaseId}
                {d.alert ? ` (${d.alert})` : ""}
              </li>
            ))}
          </ul>
        </section>
      )}
    </Stack>
  );
}
