import { useState } from 'react';
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle,
  Divider, Stack, Typography,
} from '@mui/material';
import { githubIntegrationService } from '../../services/githubIntegrationService';
import { formatApiError } from '../../services/apiError';
import type { ScanResult } from '../../types/githubIntegration';

interface Props {
  open: boolean;
  systemId: number;
  onClose: () => void;
}

export default function ScanRepositoryDialog({ open, systemId, onClose }: Props) {
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleScan = async () => {
    setScanning(true);
    setError(null);
    try {
      setResult(await githubIntegrationService.scan(systemId));
    } catch (err) {
      setError(formatApiError(err, 'Repository scan failed'));
    } finally {
      setScanning(false);
    }
  };

  const handleClose = () => {
    if (scanning) return;
    setResult(null);
    setError(null);
    onClose();
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Scan repository</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            Scans the system&apos;s GitHub repository and imports any subsystems and
            dependencies its detectors recognise.
          </Typography>

          {error && <Alert severity="error">{error}</Alert>}

          {result && (
            <Stack spacing={2}>
              <Typography variant="body2" color="text.secondary">
                Scanned ref <strong>{result.ref}</strong> — {result.files_scanned} file
                {result.files_scanned === 1 ? '' : 's'} scanned.
              </Typography>

              {result.truncated && (
                <Alert severity="warning">
                  The repository was too large to read in full — some files were not scanned.
                </Alert>
              )}

              {result.stopped_early && (
                <Alert severity="warning">
                  Scan stopped after {result.files_scanned} files.
                </Alert>
              )}

              <Divider />

              {result.detectors.map((d) => (
                <Box key={d.detector}>
                  <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 0.5 }}>
                    <Chip label={d.detector} size="small" variant="outlined" />
                    {d.paths.map((p) => (
                      <Typography key={p} variant="caption" color="text.secondary">
                        {p}
                      </Typography>
                    ))}
                  </Stack>
                  <Typography variant="body2">
                    {d.subsystems_created} subsystems created, {d.subsystems_updated} updated,{' '}
                    {d.dependencies_written} dependencies
                  </Typography>
                  {d.paths_unread > 0 && (
                    <Alert severity="warning" sx={{ mt: 1 }}>
                      {d.paths_unread} matching file{d.paths_unread === 1 ? '' : 's'} could not
                      be read because the scan hit its file limit before reaching{' '}
                      {d.paths_unread === 1 ? 'it' : 'them'}. Results above may be incomplete.
                    </Alert>
                  )}
                  {d.warnings.map((w) => (
                    <Alert key={w} severity="warning" sx={{ mt: 1 }}>
                      {w}
                    </Alert>
                  ))}
                  {d.errors.map((e) => (
                    <Alert key={e} severity="error" sx={{ mt: 1 }}>
                      {e}
                    </Alert>
                  ))}
                </Box>
              ))}
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={scanning}>Close</Button>
        <Button variant="contained" onClick={handleScan} disabled={scanning}>
          {scanning ? 'Scanning…' : 'Scan'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
