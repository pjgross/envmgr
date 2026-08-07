import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { environmentGroupService } from '../../services/environmentGroupService';
import { bookingService } from '../../services/bookingService';
import { formatApiError } from '../../services/apiError';
import type { EnvBookingSummary } from '../../types/bookingRequest';
import type { AllowedTransition } from '../../types/bookingLifecycle';
import TransitionButtons from './TransitionButtons';

type Props = {
  requestId: number;
  groupId: number;
  groupName: string;
  bookings: EnvBookingSummary[];
  // Lets the parent refresh the request after a successful group move.
  // `transitionGroup` is service-only (see environmentGroupService) — there
  // is no thunk, so the caller owns re-fetching.
  onTransitioned?: () => void | Promise<void>;
  // Per-member repair path. Members CAN diverge (see `outOfStep` below), and
  // `POST /bookings/{id}/transition` is deliberately still reachable at the
  // API as the only way out of that state — this is what makes it reachable
  // from the UI too. Mirrors `EnvironmentsPanel`'s `onTransition`: same
  // signature, same caller-owns-refresh contract.
  onMemberTransition?: (bookingId: number, toState: string, label: string) => void | Promise<void>;
};

/**
 * One group's members, rendered together, with ONE primary control set
 * driven by the group endpoint's intersection of allowed transitions — never
 * a member's own list for THAT control, which could offer a move that is
 * valid for it but not for a sibling, something the all-or-nothing group
 * transition would then refuse anyway.
 *
 * Each member row additionally carries its OWN link and its OWN
 * (individual-endpoint-driven) transition control. That is deliberate and
 * distinct from the primary control above: when members are out of step,
 * the individual endpoint is the only repair tool, and it has to be
 * reachable from right here, next to the divergence it repairs — including a
 * link to each sibling, so fixing "the other one" doesn't require hunting
 * for it in a different list.
 */
export default function GroupTransitionPanel({
  requestId,
  groupId,
  groupName,
  bookings,
  onTransitioned,
  onMemberTransition,
}: Props) {
  const [transitions, setTransitions] = useState<AllowedTransition[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [transitioning, setTransitioning] = useState(false);
  const [memberTransitions, setMemberTransitions] = useState<Record<number, AllowedTransition[]>>(
    {}
  );

  // A successful group transition (or any other state change to a member)
  // does not change `requestId`/`groupId`, so the fetch below must also key
  // on the members' states — a primitive string, not the `bookings` array
  // itself, so a parent re-render that rebuilds the array with unchanged
  // content (a risk this component doesn't control) can't trigger a refetch
  // by identity the way Finding 2 did one level up in BookingDetail.
  const statusesKey = bookings.map((b) => `${b.id}:${b.status}`).join('|');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    environmentGroupService
      .groupAllowedTransitions(requestId, groupId)
      .then((t) => {
        if (!cancelled) setTransitions(t);
      })
      .catch((err: unknown) => {
        if (!cancelled) setLoadError(formatApiError(err, 'Failed to load group transitions'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [requestId, groupId, statusesKey]);

  // Per-member allowed transitions — the individual-endpoint repair path.
  // Keyed on `statusesKey` for the same reason as the group fetch above: a
  // parent re-render that rebuilds `bookings` with unchanged ids/statuses
  // must not refetch every member's transitions again.
  const memberIdsKey = bookings.map((b) => b.id).join(',');
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const out: Record<number, AllowedTransition[]> = {};
      for (const b of bookings) {
        out[b.id] = await bookingService.getAllowedTransitions(b.id);
      }
      if (!cancelled) setMemberTransitions(out);
    };
    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberIdsKey, statusesKey]);

  // Members CAN diverge — `POST /bookings/{id}/transition` stays open as the
  // repair tool. When they have, the group transition will refuse until
  // someone repairs the odd one out, so say so here rather than let the user
  // hit an opaque refusal with no way to see why.
  const distinctStates = Array.from(new Set(bookings.map((b) => b.status)));
  const outOfStep = distinctStates.length > 1;

  const handleTransition = async (toState: string) => {
    setTransitionError(null);
    setTransitioning(true);
    try {
      await environmentGroupService.transitionGroup(requestId, groupId, { to_state: toState });
      await onTransitioned?.();
    } catch (err: unknown) {
      // service-only call — no createAsyncThunk boundary, so this catch is
      // the only place the server's message (which names every failing
      // member) can be recovered. Never set state to the raw `err`.
      setTransitionError(formatApiError(err, 'Group transition failed'));
    } finally {
      setTransitioning(false);
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Group: {groupName}
      </Typography>

      {outOfStep && (
        <Alert severity="warning" sx={{ mb: 1 }}>
          Members are out of step — the group transition will refuse until they are repaired:{' '}
          {bookings
            .map((b) => `${b.environment_name ?? `#${b.environment_id}`} (${b.status})`)
            .join(', ')}
        </Alert>
      )}

      {transitionError && (
        <Alert severity="error" sx={{ mb: 1 }} onClose={() => setTransitionError(null)}>
          {transitionError}
        </Alert>
      )}

      {loadError && (
        <Alert severity="error" sx={{ mb: 1 }}>
          {loadError}
        </Alert>
      )}

      {loading ? (
        <Skeleton variant="rectangular" height={36} sx={{ mb: 1 }} />
      ) : (
        transitions.length > 0 && (
          <Box sx={{ mb: 1 }}>
            <TransitionButtons
              transitions={transitions}
              onTransition={(toState) => {
                if (!transitioning) void handleTransition(toState);
              }}
            />
          </Box>
        )
      )}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Environment</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {bookings.map((b) => (
            <TableRow key={b.id}>
              <TableCell>
                <RouterLink to={`/bookings/${b.id}`}>
                  {b.environment_name ?? `#${b.environment_id}`}
                </RouterLink>
              </TableCell>
              <TableCell>
                <Chip size="small" label={b.status} />
              </TableCell>
              <TableCell>
                <TransitionButtons
                  transitions={memberTransitions[b.id] ?? []}
                  onTransition={(toState, label) => {
                    void onMemberTransition?.(b.id, toState, label);
                  }}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Paper>
  );
}
