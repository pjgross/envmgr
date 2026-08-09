/**
 * What A4 says about ONE conflicting pair, and the ask that follows from it.
 *
 * A4 ADVISES; IT NEVER ACTS. Nothing in this component disables, gates or hides
 * a booking action, and no copy here may read as "you cannot proceed until this
 * is resolved". An Escalate control is a request for a human decision, not a
 * gate — and even an expired escalation is rendered as a missed deadline, never
 * as a blocker. `ContentionVerdict.test.tsx`'s last describe block is the guard
 * on that, over all four outcomes and all three escalation states — including
 * the `contention-sides` line and the decision summary, which are the paths
 * most likely to acquire copy like "this must be resolved before…".
 *
 * THREE OF THE FOUR OUTCOMES HAVE NO WINNER, and each arrives with its own
 * `reason` from the server. THIS FILE RENDERS THAT STRING. It does not compose
 * an explanation of its own and it never invents an ordering: `no_project`
 * alone carries two different reasons, and the difference between them ("no
 * project" vs "archived or another tenant's") is the whole point of the second
 * one — see `contention_service`'s REASON_* constants.
 *
 * The one line this file DOES compose is the `ranked` verdict, because the
 * server deliberately expresses that as a winning booking ID plus the two
 * project names, leaving the sentence to the reader's own side. If either name
 * is missing it falls back to the server's reason rather than half a sentence.
 */
import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';

import api from '../../services/api';
import { contentionService } from '../../services/contentionService';
import { formatApiError } from '../../services/apiError';
import { addWorkingDays, localDayAsUtc, toIsoDatetime } from '../../utils/dates';
import type { EnvBookingSummary } from '../../types/bookingRequest';
import type { Contention, EscalationState } from '../../types/contention';

type Props = {
  /** The booking whose page this is — the SUBJECT of the conflicts request. */
  bookingId: number;
  /** The conflicting booking this row is about. */
  otherBooking: EnvBookingSummary;
  contention: Contention;
  /**
   * The environment group the SUBJECT booking belongs to, if any. Passed down
   * rather than looked up: `ConflictItem` carries the group for the OTHER
   * booking only, and the subject's is on the page already.
   */
  subjectGroupName: string | null;
  /**
   * The owner or a delegate of either booking, or an Admin — mirroring
   * `contention_service.assert_may_escalate`. False hides the control; it never
   * disables anything else.
   */
  canEscalate: boolean;
  /** Reload the conflicts payload — the escalation is part of it. */
  onEscalated: () => void;
};

/** How each computed state is labelled and coloured.
 *
 * `expired` is a WARNING, never an error: a missed deadline is a missed
 * deadline, and red beside a booking reads as "this booking is in trouble",
 * which is precisely the claim A4 must not make.
 */
const STATE_CHIP: Record<EscalationState, { label: string; color: 'info' | 'success' | 'warning' }> = {
  open: { label: 'Open', color: 'info' },
  answered: { label: 'Answered', color: 'success' },
  expired: { label: 'Expired', color: 'warning' },
};

const DEFAULT_RESPONSE_WORKING_DAYS = 3;

/** "YYYY-MM-DD", `days` working days from today — what a `<input type="date">` wants.
 *
 * SEEDED FROM THE READER'S OWN DAY, not from the raw instant. `addWorkingDays`
 * counts in UTC, so handing it `new Date()` asks "what day is it in UTC?" — and
 * at 09:00 in Auckland that is still yesterday, which quietly costs the named
 * owner one of the three working days the helper text promises them. `localDayAsUtc`
 * makes the start the same day the date picker below is about to display.
 */
function defaultRespondBy(): string {
  return addWorkingDays(localDayAsUtc(new Date()), DEFAULT_RESPONSE_WORKING_DAYS)
    .toISOString()
    .slice(0, 10);
}

export default function ContentionVerdict({
  bookingId,
  otherBooking,
  contention,
  subjectGroupName,
  canEscalate,
  onEscalated,
}: Props) {
  const escalation = contention.escalation;

  const [formOpen, setFormOpen] = useState(false);
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  const [ownerId, setOwnerId] = useState<number | ''>('');
  const [respondBy, setRespondBy] = useState(defaultRespondBy);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetched only once the escalator actually opens the form. A conflicts page
  // renders one of these per conflicting booking, so an unconditional fetch
  // would issue one identical request per row for a picker most readers never
  // open. GET /tenant/users/lite is bounded at its own larger contract
  // (default 1000, max 5000) — see EnvironmentDetail's owner picker.
  useEffect(() => {
    if (!formOpen) return;
    let cancelled = false;
    api
      .get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => {
        if (!cancelled) setUsers(r.data);
      })
      .catch(() => {
        if (!cancelled) setUsers([]); // the picker stays empty; nothing else breaks
      });
    return () => {
      cancelled = true;
    };
  }, [formOpen]);

  const projectNameOf = (id: number): string | null =>
    id === bookingId ? contention.booking_project_name : contention.other_project_name;

  const groupNameOf = (id: number): string | null =>
    id === bookingId ? subjectGroupName : otherBooking.environment_group_name;

  const loserId =
    contention.winner_booking_id === null
      ? null
      : contention.winner_booking_id === bookingId
        ? otherBooking.id
        : bookingId;

  // THE BOOKING THE DECISION NAMES — an answered escalation's yielding booking
  // if there is one, otherwise the side a `ranked` verdict would have give way.
  // A no-winner outcome names nobody, and nothing below may pretend otherwise.
  const namedBookingId = escalation?.decision_yields_booking_id ?? loserId;
  const namedGroupName = namedBookingId === null ? null : groupNameOf(namedBookingId);

  const winnerName =
    contention.winner_booking_id === null ? null : projectNameOf(contention.winner_booking_id);
  const loserName = loserId === null ? null : projectNameOf(loserId);

  // The composed line, or the server's reason. Composed ONLY when the outcome
  // really is `ranked` and both names are known: half a sentence naming one
  // project is worse than the reason the server already wrote.
  const composedVerdict = contention.outcome === 'ranked' && Boolean(winnerName && loserName);
  const verdictLine = composedVerdict
    ? `${winnerName} outranks ${loserName}`
    : contention.reason;

  // WHICH PROJECTS THE REASON IS ABOUT. Every no-winner reason is written in
  // the third person — "at least one booking is not linked to a project" — so
  // on its own it never says which booking, and the commonest of the five is
  // the one where it matters most: `get_project_names` deliberately does not
  // filter `deleted_at`, so an ARCHIVED project's name is available here beside
  // a verdict saying its link cannot be resolved. That pairing is the only
  // thing that makes "archived or belongs to another tenant" actionable —
  // without the name, the reader is told their register is wrong and not which
  // row is wrong. Suppressed when the verdict line already named both, and when
  // neither side has a name to give.
  const showSides = !composedVerdict && Boolean(contention.booking_project_name || contention.other_project_name);
  const sideLabel = (name: string | null) => name ?? 'no linked project';

  const submit = async () => {
    if (ownerId === '') return;
    setSaving(true);
    setError(null);
    try {
      await contentionService.escalate(bookingId, otherBooking.id, {
        owner_user_id: Number(ownerId),
        // The date input yields "YYYY-MM-DD"; `respond_by` is a datetime.
        respond_by: toIsoDatetime(respondBy) ?? respondBy,
      });
      setFormOpen(false);
      onEscalated();
    } catch (err) {
      // formatApiError IN THIS CATCH, because there is no slice thunk in front
      // of contentionService to normalise the error — `err.message` here is the
      // generic "Request failed with status code 400", and the server's reason
      // (which names why the pair cannot be escalated) is in
      // `response.data.detail`. See contentionService's module comment.
      setError(formatApiError(err, 'Failed to escalate this contention'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Box data-testid="contention-panel" sx={{ mt: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="caption" color="text.secondary">
          Project priority
        </Typography>
        <Typography variant="body2" data-testid="contention-verdict">
          {/* "No winner —" restates `winner_booking_id === null`, which is a
              fact on the response; it is not an explanation of its own. The
              explanation is the server's, unedited, immediately after it. */}
          {contention.winner_booking_id === null ? `No winner — ${verdictLine}` : verdictLine}
        </Typography>
      </Box>

      {showSides && (
        <Typography
          variant="caption"
          color="text.secondary"
          data-testid="contention-sides"
          sx={{ display: 'block', mt: 0.25 }}
        >
          This booking — {sideLabel(contention.booking_project_name)} · the conflicting booking
          — {sideLabel(contention.other_project_name)}
        </Typography>
      )}

      {namedGroupName && (
        <Typography
          variant="caption"
          color="text.secondary"
          data-testid="contention-group-note"
          sx={{ display: 'block', mt: 0.5 }}
        >
          {/* A2 transitions a group ATOMICALLY: moving the named booking moves
              every environment booked with it. Without this the line reads as
              "move this one booking", which is not what would happen. */}
          Moving that booking moves every environment in {namedGroupName} — the group was
          booked as one unit and transitions together.
        </Typography>
      )}

      {escalation ? (
        <Box
          data-testid="contention-escalation"
          sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.25 }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Typography variant="body2">
              {/* By name. `owner_username` travels with the row precisely so the
                  browser never resolves it against the capped users list. */}
              {escalation.owner_username ?? 'Someone no longer in this tenant'} to decide by{' '}
              {new Date(escalation.respond_by).toLocaleDateString()}
            </Typography>
            {/* `state` is COMPUTED SERVER-SIDE from two columns and a clock. It
                is rendered, never re-derived from `respond_by`: an expired
                escalation therefore reads as expired with no refresh and no
                scheduler, and a client clock that is wrong cannot manufacture
                a queue of phantom expiries. */}
            <Chip
              size="small"
              label={STATE_CHIP[escalation.state].label}
              color={STATE_CHIP[escalation.state].color}
              variant="outlined"
            />
          </Box>
          <Typography variant="caption" color="text.secondary">
            Raised by {escalation.escalated_by_username ?? 'someone no longer in this tenant'}
          </Typography>
          {escalation.decision_yields_booking_id !== null && (
            <Typography variant="caption" color="text.secondary">
              Decision:{' '}
              {projectNameOf(escalation.decision_yields_booking_id) ??
                'the booking with no linked project'}{' '}
              gives way
              {escalation.decision_notes ? ` — ${escalation.decision_notes}` : ''}
              {escalation.decided_by_username ? `, recorded by ${escalation.decided_by_username}` : ''}
              {escalation.decided_at
                ? ` on ${new Date(escalation.decided_at).toLocaleDateString()}`
                : ''}
            </Typography>
          )}
          {!escalation.bookings_live && (
            <Typography variant="caption" color="text.secondary">
              {/* The record OUTLIVES its bookings on purpose — it is the audit
                  trail of an argument, so it is annotated, never dropped. */}
              This contention is no longer live: one or both bookings have closed or been
              removed. The record is kept.
            </Typography>
          )}
        </Box>
      ) : (
        canEscalate && (
          <Button
            size="small"
            sx={{ mt: 0.5 }}
            onClick={() => {
              setError(null);
              setOwnerId('');
              setRespondBy(defaultRespondBy());
              setFormOpen(true);
            }}
          >
            Escalate
          </Button>
        )
      )}

      <Dialog open={formOpen} onClose={() => setFormOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>Ask someone to decide this contention</DialogTitle>
        <DialogContent>
          {/* Says what escalating does AND what it does not do, because a
              control on a booking page that mentions a decision invites the
              reading that something will be moved for you. */}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            This records the ask and the deadline. Nothing is moved or cancelled: whoever
            decides, acting on it stays with the owning team.
          </Typography>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          <TextField
            select
            fullWidth
            size="small"
            label="Decision owner"
            value={ownerId}
            onChange={(e) => setOwnerId(e.target.value ? Number(e.target.value) : '')}
            sx={{ mb: 2 }}
          >
            {users.map((u) => (
              <MenuItem key={u.id} value={u.id}>
                {u.username}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            fullWidth
            size="small"
            type="date"
            label="Respond by"
            InputLabelProps={{ shrink: true }}
            value={respondBy}
            onChange={(e) => setRespondBy(e.target.value)}
            helperText="Defaults to three working days from today. Change it if that is wrong."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={submit} disabled={saving || ownerId === ''}>
            Escalate
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
