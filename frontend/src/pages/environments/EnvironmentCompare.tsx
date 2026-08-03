/**
 * Compare two environments across presence, mocked-vs-real, deployed version
 * and host shape.
 *
 * The URL carries the whole view, so a comparison is shareable and survives a
 * refresh. `reference` is presentation only: the API returns the same
 * symmetric diff either way, and this page relabels the result.
 */
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Alert, Box, Button, CircularProgress, MenuItem, Paper, TextField, Typography,
} from '@mui/material';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { environmentComparisonService } from '../../services/environmentComparisonService';
import type { EnvironmentComparison } from '../../types/environmentComparison';

export default function EnvironmentCompare() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { environments, truncated } = useAllEnvironments();

  const left = searchParams.get('left');
  const right = searchParams.get('right');

  const [comparison, setComparison] = useState<EnvironmentComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!left || !right) {
      setComparison(null);
      return;
    }
    setLoading(true);
    setError(null);
    environmentComparisonService
      .compare(Number(left), Number(right))
      .then((result) => {
        setComparison(result);
        setError(null);
      })
      .catch((err: unknown) => {
        setComparison(null);
        setError(err instanceof Error ? err.message : 'Failed to compare environments');
      })
      .finally(() => setLoading(false));
  }, [left, right]);

  const setSide = useCallback(
    (side: 'left' | 'right', value: string) => {
      const next = new URLSearchParams(searchParams);
      if (value) next.set(side, value);
      else next.delete(side);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const swap = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    if (left) next.set('right', left);
    else next.delete('right');
    if (right) next.set('left', right);
    else next.delete('left');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, left, right]);

  return (
    <Box>
      <Typography variant="h4" gutterBottom>Compare Environments</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Differences in what each environment contains, what is mocked, which versions are
        deployed, and how each subsystem is hosted.
      </Typography>

      <Paper sx={{ p: 2, mb: 2, display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <TextField
          select size="small" label="Left" value={left ?? ''} sx={{ minWidth: 200 }}
          onChange={(e) => setSide('left', e.target.value)}
          helperText={
            truncated
              ? `Only the first ${environments.length} environments are listed.`
              : undefined
          }
        >
          {environments.map((env) => (
            <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
          ))}
        </TextField>

        <Button onClick={swap} startIcon={<SwapHorizIcon />} sx={{ mt: 0.5 }}>Swap</Button>

        <TextField
          select size="small" label="Right" value={right ?? ''} sx={{ minWidth: 200 }}
          onChange={(e) => setSide('right', e.target.value)}
        >
          {environments.map((env) => (
            <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
          ))}
        </TextField>
      </Paper>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {!left || !right ? (
        <Typography variant="body2" color="text.secondary">
          Choose two environments to compare.
        </Typography>
      ) : loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
      ) : comparison && comparison.summary.differing === 0 ? (
        <Alert severity="success">
          {comparison.left.name} and {comparison.right.name} match on all four dimensions.
        </Alert>
      ) : null}
    </Box>
  );
}
