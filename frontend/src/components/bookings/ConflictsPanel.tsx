import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  Link,
  Paper,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { bookingService } from '../../services/bookingService';
import type { ConflictItem, ReceivedFeedbackItem } from '../../types/conflict';
import { formatApiError } from '../../services/apiError';
import ContentionVerdict from './ContentionVerdict';
import ReceivedFeedbackList from './ReceivedFeedbackList';
import { formatBookingDateTime } from '../../utils/datetime';

type Props = {
  bookingId: number;
  canAcknowledge: boolean;
  /**
   * The environment group the SUBJECT booking belongs to, if any — passed
   * straight through to `ContentionVerdict`. `ConflictItem` carries the group
   * for the OTHER booking only, so without this the group note could never fire
   * for our own side, and A2 transitions a group atomically.
   */
  subjectGroupName: string | null;
  /**
   * May this user ask for a decision? Mirrors
   * `contention_service.assert_may_escalate` as closely as the page can: the
   * owner or a delegate of the SUBJECT booking, or an Admin.
   *
   * DELIBERATELY NARROWER THAN THE SERVER'S RULE, which also allows the owner
   * or a delegate of the OTHER booking. Nothing on `ConflictItem` says who owns
   * the other side, and it is not worth a per-row lookup to find out: that
   * person sees the same contention, with the control, on their own booking's
   * page. A button that 403s on click is worse than one that is absent.
   */
  canEscalate: boolean;
};

export default function ConflictsPanel({
  bookingId,
  canAcknowledge,
  subjectGroupName,
  canEscalate,
}: Props) {
  const [tab, setTab] = useState(0);
  const [items, setItems] = useState<ConflictItem[]>([]);
  const [received, setReceived] = useState<ReceivedFeedbackItem[]>([]);
  const [pending, setPending] = useState<
    Record<number, { willing_to_share: boolean; notes: string }>
  >({});
  const [conflictsError, setConflictsError] = useState<string | null>(null);
  const [receivedError, setReceivedError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingIds, setSavingIds] = useState<Set<number>>(new Set());
  const hasRendered = useRef(false);
  const reloadGen = useRef(0);

  const reload = useCallback(async () => {
    const myGen = ++reloadGen.current;
    const [conflictsRes, receivedRes] = await Promise.allSettled([
      bookingService.getConflicts(bookingId),
      bookingService.getReceivedFeedback(bookingId),
    ]);
    if (myGen !== reloadGen.current) return; // superseded — drop results
    if (conflictsRes.status === 'fulfilled') {
      setItems(conflictsRes.value);
      setConflictsError(null);
    } else {
      setConflictsError(formatApiError(conflictsRes.reason, 'Failed to load conflicts'));
    }
    if (receivedRes.status === 'fulfilled') {
      setReceived(receivedRes.value);
      setReceivedError(null);
    } else {
      setReceivedError(formatApiError(receivedRes.reason, 'Failed to load received feedback'));
    }
    setLoading(false);
  }, [bookingId]);

  useEffect(() => {
    hasRendered.current = false;
    reload();
  }, [bookingId, reload]);

  const shouldRenderNow =
    items.length > 0 || received.length > 0 || conflictsError != null || receivedError != null;

  if (shouldRenderNow) {
    hasRendered.current = true;
  }

  if (!loading && !shouldRenderNow && !hasRendered.current) return null;

  const saveAck = async (otherId: number) => {
    const p = pending[otherId] ?? { willing_to_share: false, notes: '' };
    setSavingIds((s) => new Set(s).add(otherId));
    try {
      await bookingService.acknowledgeConflict(bookingId, otherId, p);
      await reload();
    } finally {
      setSavingIds((s) => {
        const next = new Set(s);
        next.delete(otherId);
        return next;
      });
    }
  };

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        aria-label="Conflict feedback"
        sx={{ mb: 2 }}
      >
        <Tab label={`Your feedback (${items.length})`} />
        <Tab label={`Feedback received (${received.length})`} />
      </Tabs>

      {tab === 0 && (
        <Box>
          {conflictsError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setConflictsError(null)}>
              {conflictsError}
            </Alert>
          )}
          {items.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
              No conflicts for this booking.
            </Typography>
          ) : (
            items.map((it) => {
              const p = pending[it.other_booking.id] ?? {
                willing_to_share: it.ack?.willing_to_share ?? false,
                notes: it.ack?.notes ?? '',
              };
              return (
                <Box
                  key={it.other_booking.id}
                  sx={{ mb: 2, pb: 2, borderBottom: '1px solid', borderColor: 'divider' }}
                >
                  <Typography variant="body2">
                    <Link
                      component={RouterLink}
                      to={`/bookings/${it.other_booking.id}`}
                      sx={{ fontWeight: 'medium' }}
                    >
                      {it.other_booking.project_name ??
                        `Booking #${it.other_booking.id}`}
                    </Link>
                    {it.other_booking.environment_name
                      ? ` · ${it.other_booking.environment_name}`
                      : ''}
                    {' · '}
                    {formatBookingDateTime(it.other_booking.start_date)} –{' '}
                    {formatBookingDateTime(it.other_booking.end_date)}
                    {' · '}status {it.other_booking.status}
                  </Typography>
                  {/* A4's verdict, and the ask, NEXT TO THE CONDITION THEY ACT
                      ON — A2's repair-panel lesson. `contention` is required on
                      every ConflictItem, so there is nothing to guard here.
                      `reload` is the escalation's refresh: the escalation is
                      part of this very payload. */}
                  <ContentionVerdict
                    bookingId={bookingId}
                    otherBooking={it.other_booking}
                    contention={it.contention}
                    subjectGroupName={subjectGroupName}
                    canEscalate={canEscalate}
                    onEscalated={reload}
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={p.willing_to_share}
                        disabled={!canAcknowledge}
                        onChange={(e) =>
                          setPending((s) => ({
                            ...s,
                            [it.other_booking.id]: { ...p, willing_to_share: e.target.checked },
                          }))
                        }
                      />
                    }
                    label="Willing to share"
                  />
                  <TextField
                    label="Notes"
                    fullWidth
                    size="small"
                    multiline
                    minRows={2}
                    value={p.notes}
                    disabled={!canAcknowledge}
                    onChange={(e) =>
                      setPending((s) => ({
                        ...s,
                        [it.other_booking.id]: { ...p, notes: e.target.value },
                      }))
                    }
                  />
                  {canAcknowledge && (
                    <Button
                      sx={{ mt: 1 }}
                      size="small"
                      variant="contained"
                      onClick={() => saveAck(it.other_booking.id)}
                      disabled={savingIds.has(it.other_booking.id)}
                    >
                      Save
                    </Button>
                  )}
                  {it.ack?.acknowledged_at && (
                    <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                      Last updated {new Date(it.ack.acknowledged_at).toLocaleString()}
                    </Typography>
                  )}
                </Box>
              );
            })
          )}
        </Box>
      )}

      {tab === 1 && (
        <Box>
          {receivedError && (
            <Alert severity="error" sx={{ mb: 1 }} onClose={() => setReceivedError(null)}>
              {receivedError}
            </Alert>
          )}
          <ReceivedFeedbackList items={received} />
        </Box>
      )}
    </Paper>
  );
}
