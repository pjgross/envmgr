/**
 * EnvironmentRequestForm — create an environment request.
 *
 * Route: /environment-requests/new
 *
 * A mode toggle drives which fields render, mirroring the backend's own
 * split (see `_assert_mode_fields` in environment_request_service.py):
 * access requests need an environment; new-environment requests need a
 * proposed name, tier and expiry. Justification is required either way.
 * There is no `custom_fields` field here (M4): no tenant can define a
 * custom-field vocabulary for this entity, and the backend no longer
 * accepts or persists one.
 */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from '@mui/material';

import type { AppDispatch } from '../../store';
import { createEnvironmentRequest } from '../../store/environmentRequestSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { useAllEnvironmentTiers } from '../../hooks/useAllEnvironmentTiers';
import type { EnvironmentRequestCreate, EnvironmentRequestKind } from '../../types/environmentRequest';

export default function EnvironmentRequestForm() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();

  // Never a paged slice — a picker reading a server-windowed page would
  // silently offer a subset. See docs/pagination.md.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();
  const { tiers, truncated: tiersTruncated } = useAllEnvironmentTiers();

  const [kind, setKind] = useState<EnvironmentRequestKind>('access');
  const [environmentId, setEnvironmentId] = useState<number | ''>('');
  const [proposedName, setProposedName] = useState('');
  const [tierId, setTierId] = useState<number | ''>('');
  const [expiresAt, setExpiresAt] = useState('');
  const [justification, setJustification] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Mirrors the backend's own per-mode requirement (`_assert_mode_fields`):
  // access needs environment_id; new_environment needs proposed_name, tier_id
  // and expires_at. Justification is required either way.
  const isValid =
    justification.trim() !== '' &&
    (kind === 'access'
      ? environmentId !== ''
      : proposedName.trim() !== '' && tierId !== '' && expiresAt !== '');

  const handleSubmit = async () => {
    if (!isValid) return;
    setError(null);
    const data: EnvironmentRequestCreate =
      kind === 'access'
        ? {
            kind,
            justification: justification.trim(),
            environment_id: Number(environmentId),
          }
        : {
            kind,
            justification: justification.trim(),
            proposed_name: proposedName.trim(),
            tier_id: Number(tierId),
            expires_at: new Date(`${expiresAt}T00:00:00Z`).toISOString(),
          };

    setSubmitting(true);
    const result = await dispatch(createEnvironmentRequest(data));
    setSubmitting(false);

    if (createEnvironmentRequest.rejected.match(result)) {
      // `result.payload`, never `result.error.message` — the 422 here names
      // the missing field, and that message is the entire value of the
      // response. See CLAUDE.md's note on `formatApiError`/miniSerializeError.
      setError(result.payload ?? 'Failed to create the request');
      return;
    }
    navigate('/environment-requests');
  };

  return (
    <Box sx={{ p: 3, maxWidth: 640, mx: 'auto' }}>
      <Typography variant="h5" sx={{ mb: 3 }}>
        New Environment Request
      </Typography>

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          {error && <Alert severity="error">{error}</Alert>}

          <ToggleButtonGroup
            value={kind}
            exclusive
            onChange={(_, next: EnvironmentRequestKind | null) => next && setKind(next)}
            aria-label="Request kind"
          >
            <ToggleButton value="access">Access</ToggleButton>
            <ToggleButton value="new_environment">New environment</ToggleButton>
          </ToggleButtonGroup>

          {kind === 'access' ? (
            <FormControl fullWidth required>
              <InputLabel id="request-environment-label">Environment</InputLabel>
              <Select
                labelId="request-environment-label"
                label="Environment"
                value={environmentId}
                onChange={(e) => setEnvironmentId(e.target.value as number)}
              >
                {environments.map((env) => (
                  <MenuItem key={env.id} value={env.id}>
                    {env.name}
                  </MenuItem>
                ))}
              </Select>
              {environmentsTruncated && (
                <FormHelperText>
                  Only the first {environments.length} environments are shown.
                </FormHelperText>
              )}
            </FormControl>
          ) : (
            <>
              <TextField
                label="Proposed name"
                required
                fullWidth
                value={proposedName}
                onChange={(e) => setProposedName(e.target.value)}
              />
              <FormControl fullWidth required>
                <InputLabel id="request-tier-label">Tier</InputLabel>
                <Select
                  labelId="request-tier-label"
                  label="Tier"
                  value={tierId}
                  onChange={(e) => setTierId(e.target.value as number)}
                >
                  {tiers
                    .filter((t) => t.is_active)
                    .map((t) => (
                      <MenuItem key={t.id} value={t.id}>
                        {t.name}
                      </MenuItem>
                    ))}
                </Select>
                {tiersTruncated && (
                  <FormHelperText>Only the first {tiers.length} tiers are shown.</FormHelperText>
                )}
              </FormControl>
              <TextField
                label="Expiry"
                type="date"
                required
                fullWidth
                value={expiresAt}
                onChange={(e) => setExpiresAt(e.target.value)}
                InputLabelProps={{ shrink: true }}
              />
            </>
          )}

          <TextField
            label="Justification"
            required
            fullWidth
            multiline
            minRows={3}
            value={justification}
            onChange={(e) => setJustification(e.target.value)}
          />

          <Stack direction="row" spacing={2} justifyContent="flex-end" sx={{ pt: 1 }}>
            <Button onClick={() => navigate('/environment-requests')}>Cancel</Button>
            <Button variant="contained" disabled={!isValid || submitting} onClick={handleSubmit}>
              Submit request
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}
