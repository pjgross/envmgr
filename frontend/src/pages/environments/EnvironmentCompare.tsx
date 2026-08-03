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
  Alert, Box, Button, Checkbox, Chip, CircularProgress, FormControlLabel, MenuItem, Paper,
  Stack, TextField, Typography,
} from '@mui/material';
import SwapHorizIcon from '@mui/icons-material/SwapHoriz';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { environmentComparisonService } from '../../services/environmentComparisonService';
import type { DifferenceKind, EnvironmentComparison } from '../../types/environmentComparison';
import ComparisonTable, { KIND_LABEL } from '../../components/environments/ComparisonTable';

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
        // The API's `detail` says what actually went wrong; axios's own message
        // is only ever "Request failed with status code N".
        const detail =
          typeof err === 'object' && err !== null
            ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
            : undefined;
        setError(detail ?? (err instanceof Error ? err.message : 'Failed to compare environments'));
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

  const systemGaps = comparison?.systems.filter((s) => s.presence !== 'both') ?? [];

  const diffOnly = searchParams.get('diff_only') === '1';
  const reference = (searchParams.get('reference') as 'left' | 'right' | null) ?? null;

  const setFlag = useCallback(
    (key: string, value: string | null) => {
      const next = new URLSearchParams(searchParams);
      if (value === null) next.delete(key);
      else next.set(key, value);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

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
          {environments
            .filter((env) => String(env.id) !== right)
            .map((env) => (
              <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
            ))}
        </TextField>

        <Button onClick={swap} startIcon={<SwapHorizIcon />} sx={{ mt: 0.5 }}>Swap</Button>

        <TextField
          select size="small" label="Right" value={right ?? ''} sx={{ minWidth: 200 }}
          onChange={(e) => setSide('right', e.target.value)}
        >
          {environments
            .filter((env) => String(env.id) !== left)
            .map((env) => (
              <MenuItem key={env.id} value={String(env.id)}>{env.name}</MenuItem>
            ))}
        </TextField>

        <TextField
          select size="small" label="Reference" value={reference ?? ''} sx={{ minWidth: 160 }}
          onChange={(e) => setFlag('reference', e.target.value || null)}
          helperText="Frames gaps as risk against one side"
        >
          <MenuItem value="">None</MenuItem>
          <MenuItem value="left">Left</MenuItem>
          <MenuItem value="right">Right</MenuItem>
        </TextField>
        <FormControlLabel
          control={
            <Checkbox
              checked={diffOnly}
              onChange={(e) => setFlag('diff_only', e.target.checked ? '1' : null)}
            />
          }
          label="Differences only"
        />
      </Paper>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {!left || !right ? (
        <Typography variant="body2" color="text.secondary">
          Choose two environments to compare.
        </Typography>
      ) : loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}><CircularProgress /></Box>
      ) : comparison ? (
        <>
          <Paper sx={{ p: 2, mb: 2 }}>
            <Typography variant="subtitle1">
              {comparison.summary.differing} of {comparison.summary.compared} subsystems differ
            </Typography>
            <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap' }}>
              {(Object.keys(KIND_LABEL) as DifferenceKind[]).map((kind) => (
                <Chip key={kind} size="small"
                      label={`${KIND_LABEL[kind]}: ${comparison.summary.by_kind[kind]}`} />
              ))}
            </Stack>
          </Paper>
          {systemGaps.length > 0 && (
            <Alert severity="warning" sx={{ mb: 2 }}>
              {systemGaps.length === 1 ? 'One system is' : `${systemGaps.length} systems are`}{' '}
              present in only one environment:{' '}
              {systemGaps
                .map((s) => `${s.name} (only in ${s.presence === 'left_only'
                  ? comparison.left.name : comparison.right.name})`)
                .join(', ')}
              .
            </Alert>
          )}
          {comparison.summary.differing === 0 && systemGaps.length === 0 ? (
            <Alert severity="success">
              {comparison.left.name} and {comparison.right.name} match on all four dimensions.
            </Alert>
          ) : (
            <Paper>
              <ComparisonTable
                rows={diffOnly
                  ? comparison.subsystems.filter((r) => r.differences.length > 0)
                  : comparison.subsystems}
                leftName={comparison.left.name}
                rightName={comparison.right.name}
                reference={reference}
              />
            </Paper>
          )}
        </>
      ) : null}
    </Box>
  );
}
