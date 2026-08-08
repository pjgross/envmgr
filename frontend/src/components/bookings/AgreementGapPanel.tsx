import { useEffect, useState } from 'react';
import { Alert, AlertTitle, Box, Button, TextField, Typography } from '@mui/material';
import { agreementGapService } from '../../services/agreementGapService';
import { formatApiError } from '../../services/apiError';
import type { AgreementGapAckRead } from '../../types/agreementGap';

type Props = {
  bookingId: number;
  /** The server's message, or null when this booking is covered. */
  gap: string | null;
  hasUnacknowledgedGap: boolean;
  /**
   * The acknowledgement as `GET /bookings/{id}` reports it — who accepted the
   * gap, when, and with what note — or null when nobody has.
   *
   * REQUIRED, not optional, deliberately: a caller that fetches the ack and
   * forgets to pass it down is Task 6's F1 on a new prop, and every test at
   * this seam would go on passing against the nameless fallback. Required makes
   * that omission a compile error.
   *
   * It replaces the `currentUserId`/`currentUsername` pair this panel used to
   * take. The name travels with the row now (as `owner_username` and
   * `ReleaseSystemRead.system_name` do), so there is ONE source for it —
   * deliberately not a fallback pair, which is the "two mechanisms, one
   * outcome" shape that has cost this branch three findings.
   */
  gapAck: AgreementGapAckRead | null;
  /**
   * Told after a successful acknowledgement so the owner of the booking can
   * refetch it. The ack is service-only (no thunk), so the caller owns the
   * refresh — mirroring `GroupTransitionPanel`'s `onTransitioned`.
   *
   * A rejection here is the CALLER's refresh failing, not the ack failing:
   * it is deliberately not caught into this panel's error state, or a
   * recorded acknowledgement would be reported as a failed one. Callers
   * handle their own refresh errors (BookingDetail does).
   */
  onAcknowledged?: () => void | Promise<void>;
};

/**
 * One booking's usage-agreement gap (Phase 7 A3).
 *
 * A3 WARNS, IT NEVER BLOCKS. Nothing here prevents, disables or gates a
 * booking or a transition; the panel is a message plus one optional control.
 *
 * ACKNOWLEDGING IS NOT RESOLVING. An acknowledged gap still shows the gap — it
 * merely stops being unacknowledged — because the gap is computed from
 * `usage_agreement` on every read and is cleared by recording the missing
 * agreement, with no acknowledgement and no other action. The copy says so, so
 * nobody reads the button as "you must clear this first".
 *
 * There is deliberately no fetch and therefore no loading state: everything
 * except the acknowledgement the user makes here arrives as props on the
 * booking response (`agreement_gap`, `has_unacknowledged_agreement_gap`). The
 * one call that CAN fail — the ack — sets an error and re-enables its own
 * button, so a refusal leaves an actionable page rather than a permanently
 * busy control.
 */
export default function AgreementGapPanel({
  bookingId,
  gap,
  hasUnacknowledgedGap,
  gapAck,
  onAcknowledged,
}: Props) {
  const [notes, setNotes] = useState('');
  const [ack, setAck] = useState<AgreementGapAckRead | null>(null);
  const [ackError, setAckError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // An acknowledgement, a half-typed note and an error all belong to ONE
  // booking. BookingDetail re-renders this panel with new props whenever the
  // booking it displays changes, so without this reset a second booking would
  // inherit the first's "Acknowledged by …" line — state that outlives the
  // thing it describes, the shape only a second render ever exposes.
  useEffect(() => {
    setNotes('');
    setAck(null);
    setAckError(null);
  }, [bookingId]);

  if (gap == null) return null;

  // This session's acknowledgement wins over the one that arrived with the
  // booking — not two sources for one name, but the same server field read at
  // two moments: the caller refetches after `onAcknowledged`, and until that
  // lands (or if it fails) the PUT's own answer is the fresher one. Both carry
  // `acknowledged_by_username`, so the line reads identically either way.
  const shownAck = ack ?? gapAck;
  const acknowledged = shownAck != null || !hasUnacknowledgedGap;
  // Never `acknowledged_by`, which is a user id: null means "no name available",
  // and the line then reports only when it happened.
  const ackAuthor = shownAck?.acknowledged_by_username ?? null;

  const handleAcknowledge = async () => {
    setSaving(true);
    setAckError(null);
    try {
      // Service-only call — there is no createAsyncThunk boundary in front of
      // it, so this catch is the only place the server's reason can be
      // recovered. Without formatApiError the user sees "Request failed with
      // status code 404" instead of "Booking not found".
      const saved = await agreementGapService.ackGap(bookingId, notes.trim() || null);
      setAck(saved);
    } catch (err: unknown) {
      setAckError(formatApiError(err, 'Failed to acknowledge the usage-agreement gap'));
      return;
    } finally {
      setSaving(false);
    }
    await onAcknowledged?.();
  };

  return (
    <Box sx={{ mb: 2 }}>
      <Alert severity="warning">
        <AlertTitle>Usage agreement gap</AlertTitle>
        <Typography variant="body2">{gap}</Typography>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
          This is a warning only — the booking is unaffected. Recording a usage agreement that
          covers it clears this warning on its own; acknowledging records that the gap was accepted
          and creates no agreement.
        </Typography>

        {acknowledged ? (
          // The testid identifies the one line whose CONTENT varies — who and
          // when, when only when, or neither — which a text query cannot tell
          // apart. Several tests key on it.
          <Typography variant="body2" sx={{ mt: 1 }} data-testid="agreement-gap-ack">
            {shownAck != null
              ? ackAuthor
                ? `Acknowledged by ${ackAuthor} on ${new Date(shownAck.acknowledged_at).toLocaleString()}`
                : `Acknowledged on ${new Date(shownAck.acknowledged_at).toLocaleString()}`
              : // No ack row to read: the booking says the gap is acknowledged
                // and nothing more. `GET /bookings/{id}` cannot produce this
                // (an acknowledged gap HAS a row — see
                // test_the_detail_response_carries_the_acknowledgement...), and
                // since review finding I1 no page path feeds this panel a
                // non-detail BookingResponse either. It survives for a caller
                // that renders the panel from a response that never carried an
                // ack — a list row, say — and its own panel test pins that the
                // degradation is graceful rather than an id or a crash.
                'This gap has been acknowledged.'}
            {shownAck?.notes ? ` — ${shownAck.notes}` : ''}
          </Typography>
        ) : (
          <Box sx={{ mt: 1, display: 'flex', gap: 1, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <TextField
              label="Notes (optional)"
              size="small"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              sx={{ flexGrow: 1, minWidth: 240 }}
            />
            <Button
              size="small"
              variant="outlined"
              color="inherit"
              disabled={saving}
              onClick={() => {
                void handleAcknowledge();
              }}
            >
              {saving ? 'Acknowledging…' : 'Acknowledge'}
            </Button>
          </Box>
        )}
      </Alert>

      {ackError && (
        <Alert severity="error" sx={{ mt: 1 }} onClose={() => setAckError(null)}>
          {ackError}
        </Alert>
      )}
    </Box>
  );
}
