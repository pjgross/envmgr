import { useEffect, useState } from 'react';
import {
  Alert, Box, Button, CircularProgress, Link, Paper, Stack, Typography,
} from '@mui/material';
import GitHubIcon from '@mui/icons-material/GitHub';
import { githubIntegrationService } from '../../services/githubIntegrationService';
import { formatApiError } from '../../services/apiError';
import type { DeviceFlowStarted, GitHubStatus } from '../../types/githubIntegration';
import PageHeader from '../../components/layout/PageHeader';

export default function GitHubIntegration() {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [pending, setPending] = useState<DeviceFlowStarted | null>(null);
  const [starting, setStarting] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    try {
      setStatus(await githubIntegrationService.status());
    } catch (err) {
      setError(formatApiError(err, 'Failed to load GitHub integration status'));
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleConnect = async () => {
    setStarting(true);
    setError(null);
    try {
      const started = await githubIntegrationService.connect();
      setPending(started);
    } catch (err) {
      setError(formatApiError(err, 'Failed to start the GitHub device flow'));
    } finally {
      setStarting(false);
    }
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    setError(null);
    try {
      await githubIntegrationService.disconnect();
      await loadStatus();
    } catch (err) {
      setError(formatApiError(err, 'Failed to disconnect GitHub'));
    } finally {
      setDisconnecting(false);
    }
  };

  // GitHub tells us how often to poll and can raise it mid-flow with
  // `slow_down`. Honour both rather than picking our own interval: polling
  // faster than instructed is how a client gets rate-limited.
  useEffect(() => {
    if (!pending) return undefined;

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    // Persists across ticks: GitHub's `slow_down` applies to every subsequent
    // request, not just the next one. Recomputing from `pending.interval` each
    // tick would discard the backoff the server asked for.
    let intervalSeconds = pending.interval;

    const tick = () => {
      timer = setTimeout(async () => {
        if (cancelled) return;
        try {
          const result = await githubIntegrationService.poll(pending.handle);
          if (cancelled) return;
          if (result.status === 'connected') {
            setPending(null);
            const next = await githubIntegrationService.status();
            if (cancelled) return;
            setStatus(next);
            return;
          }
          if (result.status === 'denied' || result.status === 'expired') {
            setPending(null);
            setError(
              result.status === 'denied'
                ? 'Authorisation was declined on GitHub.'
                : 'The code expired before it was authorised. Start again.'
            );
            return;
          }
          if (result.status === 'slow_down') {
            // Honour the server's number when it gives one; otherwise follow
            // the device-flow convention of adding five seconds.
            intervalSeconds = result.interval ?? intervalSeconds + 5;
          }
          tick();
        } catch {
          if (!cancelled) {
            setPending(null);
            setError('Lost contact with GitHub while waiting for authorisation.');
          }
        }
      }, intervalSeconds * 1000);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [pending]);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="GitHub"
        subtitle="Connect a GitHub account so systems can scan their repository for subsystems and dependencies."
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Paper variant="outlined" sx={{ p: 3, maxWidth: 520 }}>
        {status === null && !pending && (
          <Stack direction="row" justifyContent="center" sx={{ py: 2 }}>
            <CircularProgress size={24} />
          </Stack>
        )}

        {status?.connected && (
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} alignItems="center">
              <GitHubIcon />
              <Typography>
                Connected as <strong>{status.github_login}</strong>
              </Typography>
            </Stack>
            <Box>
              <Button
                variant="outlined"
                color="error"
                onClick={handleDisconnect}
                disabled={disconnecting}
              >
                Disconnect
              </Button>
            </Box>
            <Typography variant="body2" color="text.secondary">
              Disconnecting removes the token from EnvManager. You will still need to revoke it
              in GitHub under Settings → Applications → Authorized OAuth Apps.
            </Typography>
          </Stack>
        )}

        {status && !status.connected && !pending && (
          <Stack spacing={2} alignItems="flex-start">
            <Typography color="text.secondary">Not connected.</Typography>
            <Button
              variant="contained"
              startIcon={<GitHubIcon />}
              onClick={handleConnect}
              disabled={starting}
            >
              Connect GitHub
            </Button>
            <Typography variant="body2" color="text.secondary">
              EnvManager requests the <code>repo</code> scope, which is the narrowest OAuth App
              scope that can read private repositories. It only ever reads.
            </Typography>
          </Stack>
        )}

        {pending && (
          <Stack spacing={2}>
            <Typography color="text.secondary">
              Enter this code at the verification link below to authorise EnvManager:
            </Typography>
            <Typography variant="h4" align="center" sx={{ letterSpacing: 2 }}>
              {pending.user_code}
            </Typography>
            <Typography align="center">
              <Link href={pending.verification_uri} target="_blank" rel="noopener noreferrer">
                {pending.verification_uri}
              </Link>
            </Typography>
            <Stack direction="row" spacing={1} alignItems="center" justifyContent="center">
              <CircularProgress size={16} />
              <Typography variant="body2" color="text.secondary">
                Waiting for authorisation…
              </Typography>
            </Stack>
          </Stack>
        )}
      </Paper>
    </Box>
  );
}
