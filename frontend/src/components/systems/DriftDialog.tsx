import { useState } from 'react';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, List, ListItem, ListItemText, Stack, Typography,
} from '@mui/material';
import { githubIntegrationService } from '../../services/githubIntegrationService';
import { formatApiError } from '../../services/apiError';
import type { DriftDetectorReport, DriftResult } from '../../types/githubIntegration';

interface Props {
  open: boolean;
  systemId: number;
  onClose: () => void;
}

function DetectorSection({ report }: { report: DriftDetectorReport }) {
  const { subsystems, edges } = report;

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
            In EnvManager, no longer in the code
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
                  secondary={`${c.field}: ${c.catalogue ?? '—'} → ${c.declared ?? '—'}`}
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
            {edges.missing_in_catalogue.map((e) => (
              <ListItem key={`${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText primary={`${e.from_name} → ${e.to_name}`} />
              </ListItem>
            ))}
          </List>
        </>
      )}

      {edges.missing_in_code && edges.missing_in_code.length > 0 && (
        <>
          <Typography variant="subtitle2" sx={{ mt: 1 }}>
            Dependencies in EnvManager, no longer in the code
          </Typography>
          <List dense disablePadding>
            {edges.missing_in_code.map((e) => (
              <ListItem key={`${e.from_name}-${e.to_name}`} disableGutters>
                <ListItemText primary={`${e.from_name} → ${e.to_name}`} />
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
                  secondary={`port: ${c.catalogue_port ?? '—'} → ${c.declared_port ?? '—'}`}
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

      {report.warnings.map((w) => (
        <Alert key={w} severity="warning" sx={{ mt: 1 }}>{w}</Alert>
      ))}
      {report.errors.map((e) => (
        <Alert key={e} severity="error" sx={{ mt: 1 }}>{e}</Alert>
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

              {!result.has_drift && (
                <Alert severity="success">
                  No drift found — the catalogue matches the code.
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
