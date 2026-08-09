import { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TextField,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { AppDispatch } from '../../store';
import type { RootState } from '../../store';
import { fetchBookingTypes, fetchLifecycleTemplates } from '../../store/bookingLifecycleSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { useAllEnvironments } from '../../hooks/useAllEnvironments';
import { bookingService } from '../../services/bookingService';
import { bookingRequestService } from '../../services/bookingRequestService';
import type { BookingResponse } from '../../types/booking';
import type { BookingRequestResponse, EnvBookingSummary } from '../../types/bookingRequest';
import type { BookingStatusHistory, AllowedTransition } from '../../types/bookingLifecycle';
import CustomFieldsDisplay from '../../components/CustomFieldsDisplay';
import TransitionButtons from '../../components/bookings/TransitionButtons';
import EditStandardFieldsDialog from '../../components/bookings/EditStandardFieldsDialog';
import EditCustomFieldsDialog from '../../components/bookings/EditCustomFieldsDialog';
import EnvironmentsPanel from '../../components/bookings/EnvironmentsPanel';
import GroupTransitionPanel from '../../components/bookings/GroupTransitionPanel';
import ConflictsPanel from '../../components/bookings/ConflictsPanel';
import AgreementGapPanel from '../../components/bookings/AgreementGapPanel';
import ConflictIndicator from '../../components/bookings/ConflictIndicator';
import EditEnvOverridesDialog from '../../components/bookings/EditEnvOverridesDialog';
import { formatApiError } from '../../services/apiError';

// --- Status colour map -------------------------------------------------------

const STATE_COLOURS: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  draft: 'default',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
  extension_requested: 'warning',
  closed: 'info',
};

// --- Grouping ------------------------------------------------------------

/**
 * Splits a request's bookings into one group per distinct non-null
 * `environment_group_id`, plus the hand-picked (null-group) remainder.
 *
 * Deliberately NOT a single grouped/ungrouped boolean split: a request can
 * hold bookings from two or more distinct groups side by side, and each
 * needs its own panel — collapsing on `environment_group_id != null` alone
 * would merge unrelated groups' members into one control set.
 *
 * Exported for direct unit testing of the split, independent of the render
 * tree that consumes it.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function groupBookingsByEnvironmentGroup(bookings: EnvBookingSummary[]): {
  groups: { groupId: number; groupName: string; bookings: EnvBookingSummary[] }[];
  ungrouped: EnvBookingSummary[];
} {
  const groupOrder: number[] = [];
  const groupsMap = new Map<
    number,
    { groupId: number; groupName: string; bookings: EnvBookingSummary[] }
  >();
  const ungrouped: EnvBookingSummary[] = [];

  for (const b of bookings) {
    const gid = b.environment_group_id;
    if (gid != null) {
      if (!groupsMap.has(gid)) {
        groupOrder.push(gid);
        groupsMap.set(gid, {
          groupId: gid,
          groupName: b.environment_group_name ?? `Group #${gid}`,
          bookings: [],
        });
      }
      groupsMap.get(gid)!.bookings.push(b);
    } else {
      ungrouped.push(b);
    }
  }

  return { groups: groupOrder.map((gid) => groupsMap.get(gid)!), ungrouped };
}

// --- Component ---------------------------------------------------------------

export default function BookingDetail() {
  const { id } = useParams<{ id: string }>();
  const bookingId = Number(id);
  const navigate = useNavigate();
  const dispatch = useDispatch<AppDispatch>();
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['booking'] ?? []
  );
  const bookingTypes = useSelector((state: RootState) => state.bookingLifecycle.bookingTypes);
  const currentUser = useSelector((state: RootState) => state.auth.user);
  // Not the shared environment slice: since the C3 conversion it
  // is EnvironmentList's current filtered page, so the add-environment picker
  // below would silently offer a subset.
  const { environments, truncated: environmentsTruncated } = useAllEnvironments();

  // Local state
  const [booking, setBooking] = useState<BookingResponse | null>(null);
  const [bookingRequest, setBookingRequest] = useState<BookingRequestResponse | null>(null);
  const [allowedTransitions, setAllowedTransitions] = useState<AllowedTransition[]>([]);
  const [history, setHistory] = useState<BookingStatusHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingCustomFields, setEditingCustomFields] = useState(false);
  const [editingStandardFields, setEditingStandardFields] = useState(false);
  const [editingEnvOverrides, setEditingEnvOverrides] = useState(false);
  const [addEnvOpen, setAddEnvOpen] = useState(false);

  // Add-env dialog local state
  const [addEnvId, setAddEnvId] = useState<number | ''>('');
  const [addEnvStart, setAddEnvStart] = useState('');
  const [addEnvEnd, setAddEnvEnd] = useState('');
  const [addEnvSaving, setAddEnvSaving] = useState(false);

  // Load on mount
  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates('booking'));
    dispatch(fetchDefinitions('booking'));

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [b, transitions, hist] = await Promise.all([
          bookingService.getBooking(bookingId),
          bookingService.getAllowedTransitions(bookingId),
          bookingService.getHistory(bookingId),
        ]);
        setBooking(b);
        setAllowedTransitions(transitions);
        setHistory(hist);

        // Fetch request if available (may be null for legacy rows)
        if (b.booking_request_id != null) {
          try {
            const req = await bookingRequestService.get(b.booking_request_id);
            setBookingRequest(req);
          } catch {
            // Legacy row or request not found — leave bookingRequest null
          }
        }
      } catch (err: unknown) {
        setError(formatApiError(err, 'Failed to load booking'));
      } finally {
        setLoading(false);
      }
    };

    load();
  }, [bookingId, dispatch]);

  // Transition handler (used for top-level booking transitions outside EnvironmentsPanel)
  const handleTransition = async (toState: string, label: string) => {
    const notes =
      toState === 'draft' ? (window.prompt(`Reason for "${label}":`) ?? undefined) : undefined;
    try {
      await bookingService.transitionState(bookingId, toState, notes);
      const [updated, transitions, hist] = await Promise.all([
        bookingService.getBooking(bookingId),
        bookingService.getAllowedTransitions(bookingId),
        bookingService.getHistory(bookingId),
      ]);
      setBooking(updated);
      setAllowedTransitions(transitions);
      setHistory(hist);
    } catch (err: unknown) {
      setError(formatApiError(err, 'Transition failed'));
    }
  };

  // Shared repair-path handler: transitions a single booking via the
  // individual endpoint, then refreshes the request (and the top booking, if
  // it's the one that moved). Used both by `EnvironmentsPanel` (hand-picked
  // environments) and by `GroupTransitionPanel`'s per-member controls — the
  // individual endpoint is deliberately still reachable there as the only
  // way to repair a group that has gone out of step (see Finding 1).
  const handleMemberTransition = async (id: number, toState: string, label: string) => {
    if (!bookingRequest || !booking) return;
    const notes =
      toState === 'draft' ? (window.prompt(`Reason for "${label}":`) ?? undefined) : undefined;
    try {
      await bookingService.transitionState(id, toState, notes);
      const req = await bookingRequestService.get(bookingRequest.id);
      setBookingRequest(req);
      if (id === booking.id) {
        const b = await bookingService.getBooking(id);
        setBooking(b);
      }
    } catch (err: unknown) {
      setError(formatApiError(err, 'Transition failed'));
    }
  };

  // Reset add-env dialog fields
  const resetAddEnvForm = () => {
    setAddEnvId('');
    setAddEnvStart('');
    setAddEnvEnd('');
  };

  // Add-env confirm handler
  const handleAddEnvConfirm = async () => {
    if (!bookingRequest || addEnvId === '') return;
    setAddEnvSaving(true);
    try {
      await bookingRequestService.addEnvironment(bookingRequest.id, {
        environment_id: addEnvId as number,
        start_date: addEnvStart || undefined,
        end_date: addEnvEnd || undefined,
      });
      const req = await bookingRequestService.get(bookingRequest.id);
      setBookingRequest(req);
      setAddEnvOpen(false);
      resetAddEnvForm();
    } catch (err: unknown) {
      setError(formatApiError(err, 'Failed to add environment'));
    } finally {
      setAddEnvSaving(false);
    }
  };

  // One GroupTransitionPanel per distinct group on the request; everything
  // else (hand-picked environments) stays in EnvironmentsPanel exactly as
  // before. The distinction the split preserves is grouping for the
  // ALL-OR-NOTHING transition (one intersection-driven control per group,
  // vs. one independent control per hand-picked booking) — both panels give
  // every member its own link and its own individual-endpoint repair
  // control, since that endpoint is the only way to fix a diverged group.
  //
  // Memoized on the `bookings` array reference (must run unconditionally, on
  // every render, ahead of the early returns below — a hook cannot follow a
  // conditional `return`). This used to be computed directly in the render
  // body, which built new `groups`/`ungrouped` arrays on every render —
  // including ones with no relevant change (typing into the Add-Environment
  // dialog, etc). `EnvironmentsPanel`'s own effect keys on `envBookings` by
  // identity, so a fresh `ungrouped` array reference every render refetched
  // every hand-picked booking's transitions on any unrelated state change.
  // Keying on `bookingRequest?.bookings` keeps the same array reference —
  // and so the same `ungrouped` reference — across renders where the
  // underlying bookings haven't changed.
  const { groups: bookingGroups, ungrouped: ungroupedBookings } = useMemo(
    () => groupBookingsByEnvironmentGroup(bookingRequest?.bookings ?? []),
    [bookingRequest?.bookings]
  );

  // --- Render states ---

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !booking) {
    return (
      <Box sx={{ p: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/bookings/list')}
          sx={{ mb: 2 }}
        >
          Back to Bookings
        </Button>
        <Alert severity="error">{error}</Alert>
      </Box>
    );
  }

  if (!booking) return null;

  // Environments already in this request (to exclude from add-env picker) —
  // deliberately every booking, grouped and hand-picked alike.
  const existingEnvIds = new Set((bookingRequest?.bookings ?? []).map((b) => b.environment_id));
  const availableEnvs = environments.filter((e) => !existingEnvIds.has(e.id));

  // --- Main render ---

  return (
    <Box sx={{ p: 3, maxWidth: 900 }}>
      {/* Back button */}
      <Button
        startIcon={<ArrowBackIcon />}
        onClick={() => navigate('/bookings/list')}
        sx={{ mb: 2 }}
      >
        Back to Bookings
      </Button>

      {/* Request context */}
      {booking.request && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Typography variant="h6">{booking.request.project_name}</Typography>
            <ConflictIndicator hasUnacknowledged={booking.has_unacknowledged_conflicts} />
            <Box sx={{ flexGrow: 1 }} />
            {bookingRequest != null && (
              <Button size="small" onClick={() => setEditingStandardFields(true)}>
                Edit request
              </Button>
            )}
          </Box>
        </Paper>
      )}

      {/* Booking status chip (for context when no request block shows, or as supplementary info) */}
      {!booking.request && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
          <Typography variant="h5" fontWeight="bold">
            {booking.project_name}
          </Typography>
          <Chip
            label={booking.status}
            color={STATE_COLOURS[booking.status] ?? 'default'}
            size="small"
          />
        </Box>
      )}

      {/* Error banner (transition errors) */}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {/* Usage-agreement gap (A3) — rendered next to the booking it warns
          about, ahead of the transition controls, because it is a standing
          governance finding about THIS booking rather than a result of
          anything the user just did. It gates nothing: A3 warns and never
          blocks, so no control below is disabled or hidden on its account,
          and the panel renders nothing at all when the booking is covered. */}
      <AgreementGapPanel
        bookingId={booking.id}
        gap={booking.agreement_gap}
        hasUnacknowledgedGap={booking.has_unacknowledged_agreement_gap}
        // Who accepted the gap and when, straight off the detail response —
        // which is what makes "who and when" survive a reload. `?? null`
        // because the field is detail-only: a BookingResponse from a PATCH or
        // a transition carries no key at all, and the panel's prop is
        // deliberately required so forgetting it cannot compile.
        gapAck={booking.agreement_gap_ack ?? null}
        onAcknowledged={async () => {
          // The ack is service-only (no thunk), so the refresh is the
          // caller's. Refetching is what makes the ACKNOWLEDGED state
          // survive a reload — and the gap itself deliberately survives
          // with it: acknowledging is not resolving.
          try {
            const updated = await bookingService.getBooking(booking.id);
            setBooking(updated);
            if (bookingRequest != null) {
              const req = await bookingRequestService.get(bookingRequest.id);
              setBookingRequest(req);
            }
          } catch (err: unknown) {
            // The acknowledgement itself succeeded; only the refresh failed.
            // Caught here rather than in the panel so it is never reported as
            // a failed acknowledgement.
            setError(formatApiError(err, 'Failed to refresh the booking'));
          }
        }}
      />

      {/* GroupTransitionPanel — one per distinct environment group on the
          request. The panel offers a primary control set driven by the
          group's allowed-transitions intersection, PLUS a per-member link
          and individual-endpoint transition control — the repair path for
          when members have diverged. phase-7.md's own design trade: forbidding
          the individual endpoint would convert a recoverable mess into a
          stuck one, so it stays open — and reachable, which is the fix for
          final-review Finding 1. */}
      {bookingRequest &&
        bookingGroups.map((g) => (
          <GroupTransitionPanel
            key={g.groupId}
            requestId={bookingRequest.id}
            groupId={g.groupId}
            groupName={g.groupName}
            bookings={g.bookings}
            onTransitioned={async () => {
              const req = await bookingRequestService.get(bookingRequest.id);
              setBookingRequest(req);
              if (g.bookings.some((m) => m.id === booking.id)) {
                const b = await bookingService.getBooking(booking.id);
                setBooking(b);
              }
            }}
            onMemberTransition={handleMemberTransition}
          />
        ))}

      {/* EnvironmentsPanel — hand-picked (null-group) envs only; group
          members render in their own GroupTransitionPanel above, never here. */}
      {bookingRequest && (
        <EnvironmentsPanel
          requestId={bookingRequest.id}
          envBookings={ungroupedBookings}
          highlightBookingId={booking.id}
          onTransition={handleMemberTransition}
          onRemove={async (id) => {
            try {
              await bookingRequestService.removeEnvironment(bookingRequest.id, id);
              const req = await bookingRequestService.get(bookingRequest.id);
              setBookingRequest(req);
            } catch (err: unknown) {
              setError(formatApiError(err, 'Failed to remove environment'));
            }
          }}
          onAddClick={() => setAddEnvOpen(true)}
        />
      )}

      {/* Legacy (no request): show transition buttons */}
      {!bookingRequest && allowedTransitions.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <TransitionButtons transitions={allowedTransitions} onTransition={handleTransition} />
        </Box>
      )}

      {/* Booking details — env-level info */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
          <Button size="small" onClick={() => setEditingEnvOverrides(true)}>
            Edit dates
          </Button>
        </Box>
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            rowGap: 1.5,
            columnGap: 2,
          }}
        >
          <Typography variant="body2" color="text.secondary">
            Environment
          </Typography>
          <Typography variant="body2">{booking.environment_name ?? '—'}</Typography>

          <Typography variant="body2" color="text.secondary">
            Status
          </Typography>
          <Box>
            <Chip
              label={booking.status}
              color={STATE_COLOURS[booking.status] ?? 'default'}
              size="small"
            />
          </Box>

          <Typography variant="body2" color="text.secondary">
            Booked By
          </Typography>
          <Typography variant="body2">{booking.booked_by_username ?? '—'}</Typography>

          <Typography variant="body2" color="text.secondary">
            Start Date
          </Typography>
          <Typography variant="body2">
            {new Date(booking.start_date).toLocaleDateString()}
          </Typography>

          <Typography variant="body2" color="text.secondary">
            End Date
          </Typography>
          <Typography variant="body2">{new Date(booking.end_date).toLocaleDateString()}</Typography>

          {!bookingRequest && (
            <>
              <Typography variant="body2" color="text.secondary">
                Purpose
              </Typography>
              <Typography variant="body2">{booking.project_name}</Typography>

              <Typography variant="body2" color="text.secondary">
                Exclusive Use
              </Typography>
              <Box>
                <Chip
                  label={booking.exclusive_use ? 'Yes' : 'No'}
                  color={booking.exclusive_use ? 'warning' : 'default'}
                  size="small"
                />
              </Box>

              <Typography variant="body2" color="text.secondary">
                Context Tag
              </Typography>
              <Typography variant="body2">{booking.context_tag}</Typography>

              <Typography variant="body2" color="text.secondary" sx={{ pt: 0.5 }}>
                Notes
              </Typography>
              <Typography variant="body2">{booking.notes ?? '—'}</Typography>
            </>
          )}
        </Box>
      </Paper>

      {/* ConflictsPanel */}
      <ConflictsPanel
        bookingId={booking.id}
        canAcknowledge={
          Boolean(currentUser) &&
          (currentUser!.id === bookingRequest?.booked_by ||
            (bookingRequest?.delegate_user_ids ?? []).includes(currentUser!.id))
        }
        // A4's group note needs the SUBJECT booking's group, which only this
        // page knows: `ConflictItem` carries the group of the OTHER booking.
        subjectGroupName={booking.environment_group_name}
        // Mirrors `assert_may_escalate` as closely as this page can — see
        // ConflictsPanel's prop docs for why the other booking's owner is not
        // covered here. Admin included, master admin with them, the way every
        // other gate in this app treats the two.
        canEscalate={
          Boolean(currentUser) &&
          (currentUser!.id === bookingRequest?.booked_by ||
            (bookingRequest?.delegate_user_ids ?? []).includes(currentUser!.id) ||
            currentUser!.role === 'Admin' ||
            currentUser!.is_master_admin === true)
        }
      />

      {/* Custom Fields */}
      {(() => {
        const perms = booking.custom_field_permissions ?? {};
        const visibleDefs = customFieldDefs.filter((d) => d.field_key in perms);
        const editableDefs = visibleDefs.filter((d) => perms[d.field_key]?.editable);
        if (visibleDefs.length === 0) return null;
        return (
          <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
            <Box
              sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
            >
              <Typography variant="subtitle2">Custom Fields</Typography>
              {editableDefs.length > 0 && bookingRequest != null && (
                <Button size="small" onClick={() => setEditingCustomFields(true)}>
                  Edit
                </Button>
              )}
            </Box>
            <CustomFieldsDisplay definitions={visibleDefs} values={booking.custom_fields} />
          </Paper>
        );
      })()}

      <Divider />

      {/* History */}
      <Box sx={{ mt: 3 }}>
        <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
          History
        </Typography>
        {history.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No history yet.
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {history.map((row) => (
              <Box
                key={row.id}
                sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}
              >
                <Typography variant="caption" color="text.secondary" sx={{ minWidth: 150 }}>
                  {new Date(row.changed_at).toLocaleString()}
                </Typography>
                {row.from_state ? (
                  <>
                    <Chip label={row.from_state} size="small" />
                    <Typography variant="caption">→</Typography>
                    <Chip label={row.to_state} size="small" color="primary" />
                  </>
                ) : (
                  <>
                    <Typography variant="caption">Created as</Typography>
                    <Chip label={row.to_state} size="small" />
                  </>
                )}
                {row.notes && (
                  <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                    {row.notes}
                  </Typography>
                )}
              </Box>
            ))}
          </Box>
        )}
      </Box>

      {/* Edit Standard Fields Dialog — points at request-level update */}
      {booking && bookingRequest != null && (
        <EditStandardFieldsDialog
          open={editingStandardFields}
          booking={booking}
          bookingTypes={bookingTypes}
          onClose={() => setEditingStandardFields(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking);
            // Also refresh the request (mirrors project_name, dates, etc.)
            const req = await bookingRequestService.get(bookingRequest.id);
            setBookingRequest(req);
          }}
          saver={async (payload) => {
            await bookingRequestService.updateStandardFields(bookingRequest.id, payload);
            // Re-fetch booking to get mirrored fields
            return bookingService.getBooking(bookingId);
          }}
          onError={setError}
        />
      )}

      {/* Edit Custom Fields Dialog — points at request-level update */}
      {booking && bookingRequest != null && (
        <EditCustomFieldsDialog
          open={editingCustomFields}
          booking={booking}
          definitions={customFieldDefs}
          onClose={() => setEditingCustomFields(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking);
            const req = await bookingRequestService.get(bookingRequest.id);
            setBookingRequest(req);
          }}
          saver={async (values) => {
            await bookingRequestService.updateCustomFields(bookingRequest.id, values);
            return bookingService.getBooking(bookingId);
          }}
          onError={setError}
        />
      )}

      {/* Edit Env Overrides Dialog — env-level date edit */}
      {booking && (
        <EditEnvOverridesDialog
          open={editingEnvOverrides}
          booking={booking}
          onClose={() => setEditingEnvOverrides(false)}
          onSaved={async (updatedBooking) => {
            setBooking(updatedBooking);
            if (bookingRequest != null) {
              const req = await bookingRequestService.get(bookingRequest.id);
              setBookingRequest(req);
            }
          }}
          // Refetch rather than return the PATCH's own answer, exactly as the
          // two dialogs above do. `PATCH /bookings/{id}/standard-fields` is not
          // the detail read, so its BookingResponse carries `agreement_gap_ack:
          // null` — feeding that straight into `setBooking` would wipe "who
          // acknowledged this gap, and when" off a page that was showing it,
          // until the next full load. Review finding I1; guarded by
          // `keeps the earlier session's acknowledger on the page after an
          // env-override save`.
          saver={async (payload) => {
            await bookingService.updateStandardFields(bookingId, payload);
            return bookingService.getBooking(bookingId);
          }}
          onError={setError}
        />
      )}

      {/* Add Environment Dialog */}
      <Dialog
        open={addEnvOpen}
        onClose={() => {
          setAddEnvOpen(false);
          resetAddEnvForm();
        }}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>Add Environment</DialogTitle>
        <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <FormControl fullWidth size="small">
            <InputLabel>Environment</InputLabel>
            <Select
              label="Environment"
              value={addEnvId}
              onChange={(e) => setAddEnvId(e.target.value as number)}
            >
              {availableEnvs.map((env) => (
                <MenuItem key={env.id} value={env.id}>
                  {env.name}
                </MenuItem>
              ))}
            </Select>
            {environmentsTruncated && (
              <FormHelperText>Only the first {environments.length} environments are shown.</FormHelperText>
            )}
          </FormControl>
          <TextField
            label="Start Date (optional)"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={addEnvStart}
            onChange={(e) => setAddEnvStart(e.target.value)}
          />
          <TextField
            label="End Date (optional)"
            type="date"
            size="small"
            InputLabelProps={{ shrink: true }}
            value={addEnvEnd}
            onChange={(e) => setAddEnvEnd(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setAddEnvOpen(false);
              resetAddEnvForm();
            }}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={addEnvId === '' || addEnvSaving}
            onClick={handleAddEnvConfirm}
          >
            {addEnvSaving ? 'Adding…' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
