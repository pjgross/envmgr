/**
 * WelcomePack — the six-section handover document a requester reads once
 * their environment-request has been fulfilled.
 *
 * Rendered live from GET /environment-requests/{id}/welcome-pack, which
 * 409s unless the request is `fulfilled` — this component is only ever
 * mounted from EnvironmentRequestDetail once that is true.
 *
 * The backend already substitutes "Not provided" for every empty free-text
 * field (see WelcomePackResponse's docstring) specifically so a blank
 * section doesn't read as "there is nothing to do". Every heading below is
 * therefore rendered unconditionally — no falsy check hides a section, which
 * would recreate exactly the confusion the backend's fallback exists to
 * prevent.
 *
 * `support.operations_group_members` travels with the response as a
 * `string[]` and is rendered directly. It is deliberately NOT resolved by
 * fetching `/tenant/users/lite` — that endpoint is capped, and a `.find()`
 * miss would render a real team member as "—", silently losing information.
 */
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Alert, Box, Chip, Divider, Paper, Stack, Typography } from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchWelcomePack } from '../../store/environmentRequestSlice';

interface WelcomePackProps {
  requestId: number;
}

function asText(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  return String(value);
}

export default function WelcomePack({ requestId }: WelcomePackProps) {
  const dispatch = useDispatch<AppDispatch>();
  // welcomePackError, NEVER the slice-wide `error` — that field is also
  // written by fetchEnvironmentRequest/fetchEnvironmentRequests, so reading
  // it here would render an unrelated request-list or request-detail
  // failure as if it were the pack's own.
  const { welcomePack, welcomePackError } = useSelector(
    (state: RootState) => state.environmentRequest
  );

  useEffect(() => {
    dispatch(fetchWelcomePack(requestId));
  }, [dispatch, requestId]);

  if (!welcomePack) {
    return welcomePackError ? <Alert severity="error">{welcomePackError}</Alert> : null;
  }

  const { environment, access, support, caveats, offboarding, context } = welcomePack;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        Welcome Pack
      </Typography>

      <Stack spacing={2.5} divider={<Divider />}>
        <Box>
          <Typography variant="overline" color="text.secondary">
            Environment
          </Typography>
          <Typography variant="body1" fontWeight="medium">
            {asText(environment.name)}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
            <Chip size="small" label={`Tier: ${asText(environment.tier)}`} />
            <Chip size="small" label={`Status: ${asText(environment.status)}`} />
          </Stack>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            Owner: {asText(environment.owner)}
          </Typography>
          <Typography variant="body2">
            Expires:{' '}
            {environment.expires_at
              ? new Date(String(environment.expires_at)).toLocaleDateString()
              : 'No expiry planned'}
          </Typography>
        </Box>

        <Box>
          <Typography variant="overline" color="text.secondary">
            How to connect
          </Typography>
          <Typography variant="body2">Access URL: {access.access_url}</Typography>
          <Typography variant="body2">{access.connection_notes}</Typography>
          <Typography variant="body2">Support contact: {access.support_contact}</Typography>
        </Box>

        <Box>
          <Typography variant="overline" color="text.secondary">
            Support
          </Typography>
          <Typography variant="body2">SLA: {support.sla_notes}</Typography>
          <Typography variant="body2">Operating team: {support.operations_group}</Typography>
          <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap' }}>
            {support.operations_group_members.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No members
              </Typography>
            ) : (
              support.operations_group_members.map((name) => (
                <Chip key={name} size="small" label={name} />
              ))
            )}
          </Stack>
        </Box>

        <Box>
          <Typography variant="overline" color="text.secondary">
            Known limitations
          </Typography>
          <Typography variant="body2">{caveats.known_limitations}</Typography>
        </Box>

        <Box>
          <Typography variant="overline" color="text.secondary">
            Offboarding
          </Typography>
          <Typography variant="body2">{offboarding.decommission_notes}</Typography>
        </Box>

        <Box>
          <Typography variant="overline" color="text.secondary">
            Context
          </Typography>
          <Typography variant="body2">Requested by: {asText(context.requested_by)}</Typography>
          <Typography variant="body2">Justification: {asText(context.justification)}</Typography>
          <Typography variant="body2">Kind: {asText(context.kind)}</Typography>
        </Box>
      </Stack>
    </Paper>
  );
}
