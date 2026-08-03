import { useState } from 'react';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, List, ListItem, ListItemText, Stack, Typography,
} from '@mui/material';
import { githubIntegrationService } from '../../services/githubIntegrationService';
import { formatApiError } from '../../services/apiError';
import type { DriftDetectorReport, DriftEdge, DriftResult } from '../../types/githubIntegration';

interface Props {
  open: boolean;
  systemId: number;
  onClose: () => void;
}

// port is the only comparable edge attribute — the sole thing that can make
// an edge "changed" — so it belongs alongside the from/to names, not dropped.
// source_path is shown for the same reason it's shown for subsystems: as
// context for where the claim came from.
function edgeContext(e: DriftEdge): string | undefined {
  const parts: string[] = [];
  if (e.port != null) parts.push(`port ${e.port}`);
  if (e.source_path) parts.push(e.source_path);
  return parts.length > 0 ? parts.join(' · ') : undefined;
}

function DetectorSection({ report }: { report: DriftDetectorReport }) {
  const { subsystems, edges } = report;

  // The compose detector deliberately never claims override/fragment files
  // (docker-compose.override.yml, .prod.yml, ...) — parsing one alone would
  // import a partial service list as the whole application. But a system can
  // be seeded from one of those files by a separate import, so this detector
  // can read every path it claimed, compute absence, and still be asserting
  // "gone from the code" against a repository it never looked at for that
  // path. Name what was actually read rather than say "the code" in general.
  const readBasis = report.paths.length > 0
    ? `no longer in ${report.paths.join(', ')}`
    : 'not found — but this check read no files';

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
        <Chip label={report.detector} size="small" variant="outlined" />
        {report.paths.map((p) => (
          <Typography key={p} variant="caption" color="text.secondary">{p}</Typography>
        ))}
      </Stack>

      {!report.absence_computed && report.absence_reason && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          {report.absence_reason} Subsystems and dependencies that are no longer
          declared could not be checked.
        </Alert>
      )}

      {subsystems.missing_in_catalogue.length > 0 && (
        <>
          <Typography variant="subtitle2">Declared in the code, not in EnvManager</Typography>
          <List dense disablePadding>
            {subsystems.missing_in_catalogue.map((s) => (
              <ListItem key={s.name} disableGutters>
                <ListItemText
                  primary={s.name}
                  secondary={`${s.component_type}${s.technology ? ` · ${s.technology}` : ''} · ${s.source_path}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {/* Rendered only when absence was computed. An empty list under this
          heading would read as "nothing is missing" — the opposite conclusion
          to "we could not check". */}
      {subsystems.missing_in_code && subsystems.missing_in_code.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            In EnvManager, {readBasis}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Scanning will not remove these — the scanner never deletes.
          </Typography>
          <List dense disablePadding>
            {subsystems.missing_in_code.map((name) => (
              <ListItem key={name} disableGutters>
                <ListItemText primary={name} />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {subsystems.changed.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>Changed</Typography>
          <List dense disablePadding>
            {subsystems.changed.map((c) => (
              <ListItem key={`${c.name}-${c.field}`} disableGutters>
                <ListItemText
                  primary={c.name}
                  secondary={`${c.field}: ${c.catalogue ?? '—'} → ${c.declared ?? '—'} · ${c.source_path}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.missing_in_catalogue.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Dependencies declared in the code, not in EnvManager
          </Typography>
          <List dense disablePadding>
            {edges.missing_in_catalogue.map((e, i) => (
              <ListItem key={`${i}-${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText
                  primary={`${e.from_name} → ${e.to_name}`}
                  secondary={edgeContext(e)}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.missing_in_code && edges.missing_in_code.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Dependencies in EnvManager, {readBasis}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Scanning will remove these — unlike subsystems, dependency edges
            are deleted and rewritten from what the code declares on every scan.
          </Typography>
          <List dense disablePadding>
            {edges.missing_in_code.map((e, i) => (
              <ListItem key={`${i}-${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText
                  primary={`${e.from_name} → ${e.to_name}`}
                  secondary={edgeContext(e)}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.changed.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>Dependencies changed</Typography>
          <List dense disablePadding>
            {edges.changed.map((c) => (
              <ListItem key={`${c.from_name}-${c.to_name}`} disableGutters>
                <ListItemText
                  primary={`${c.from_name} → ${c.to_name}`}
                  secondary={`port: ${c.catalogue_port ?? '—'} → ${c.declared_port ?? '—'} · ${c.source_path}`}
                />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {!report.has_drift && report.absence_computed && (
        <Typography variant="body2" color="text.secondary">
          No drift detected by this detector.
        </Typography>
      )}

      {report.warnings.map((w, i) => (
        // Keyed by index, not message: parse_terraform_hcl (and others) can
        // emit the identical warning string for two different files.
        <Alert key={`warning-${i}`} severity="warning" sx={{ mt: 1 }}>{w}</Alert>
      ))}
      {report.errors.map((e, i) => (
        <Alert key={`error-${i}`} severity="error" sx={{ mt: 1 }}>{e}</Alert>
      ))}
    </Box>
  );
}

export default function DriftDialog({ open, systemId, onClose }: Props) {
  const [checking, setChecking] = useState(false);
  const [result, setResult] = useState<DriftResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleCheck = async () => {
    setChecking(true);
    setError(null);
    try {
      setResult(await githubIntegrationService.drift(systemId));
    } catch (err) {
      setError(formatApiError(err, 'Drift check failed'));
      // A failed re-check must not leave the previous report on screen under
      // the new error banner — that reads as a current, verified result.
      setResult(null);
    } finally {
      setChecking(false);
    }
  };

  const handleClose = () => {
    if (checking) return;
    setResult(null);
    setError(null);
    onClose();
  };

  // has_drift is computed only from the categories each detector managed to
  // compute; a null absence category contributes nothing to it. The
  // unqualified success banner is only honest when every detector's absence
  // WAS computed.
  const allAbsenceComputed = result?.detectors.every((d) => d.absence_computed) ?? true;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Repository drift</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Compares this system&apos;s subsystems against what its GitHub repository
            declares. Nothing is written — use Scan repository to apply changes.
          </Typography>

          {error && <Alert severity="error">{error}</Alert>}

          {result && (
            <Stack spacing={2}>
              <Typography variant="body2" color="text.secondary">
                Checked ref <strong>{result.ref}</strong> — {result.files_scanned} file
                {result.files_scanned === 1 ? '' : 's'} read.
              </Typography>

              {!result.has_drift && allAbsenceComputed && (
                <Alert severity="success">
                  No drift found — the catalogue matches the code.
                </Alert>
              )}

              {/* has_drift is computed only from the categories that WERE
                  computed, so a partial read with nothing concretely
                  different still yields has_drift=false. The success banner
                  above must not appear then — it would sit directly above a
                  truncation warning, claiming a clean bill of health in the
                  same breath as saying it couldn't check. */}
              {!result.has_drift && !allAbsenceComputed && (
                <Alert severity="warning">
                  No differences found in the parts of the repository that
                  could be read — this is not a clean bill of health.
                </Alert>
              )}

              <Divider />

              {result.detectors.map((d) => (
                <DetectorSection key={d.detector} report={d} />
              ))}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={checking}>Close</Button>
        <Button variant="contained" onClick={handleCheck} disabled={checking}>
          {checking ? 'Checking…' : 'Check drift'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
