/**
 * DecommissionPanel — B5 Task 12. The one surface that drives the whole
 * decommission workflow: the banner, every control the viewer may actually
 * use, and the attestation checklist, ALL TOGETHER in one panel.
 *
 * A2's `GroupTransitionPanel` lesson, restated for B5: a banner that
 * diagnoses a state and offers no way to act on it is where three tasks
 * quietly removed the repair affordance. Controls live next to the state
 * they act on — there is no separate "actions" section here.
 *
 * PERMISSION SPLIT, MIRRORED FROM THE SERVER (see
 * `environment_decommission_service.assert_may_run` /
 * `assert_may_defend`):
 *   - "Run" actions (initiate, decide an extension, sign a step, tear down,
 *     cancel) — the environment's operating team, or Admin/master admin.
 *   - "Defend" actions (request an extension) — the environment's NAMED
 *     OWNER, or Admin/master admin. Deliberately NOT gated on team
 *     membership: the person defending an environment is by definition not
 *     on the team decommissioning it (B3b's mistake, corrected there).
 * Team membership is not on the frontend's user object (same gap
 * `HandoverSection` hit first), so it is resolved the same way: fetched here
 * via `userGroupService.listMembers`, falling back to NOT a member on any
 * error or missing group — a network failure must never widen who can act.
 *
 * ATTESTATION HISTORY — A DISCLOSED GAP. There is no `GET` for previously
 * signed attestations (`POST .../attestations` is write-only; the backend is
 * feature-complete as of Task 9 with no such route). `decommission` may
 * optionally carry a pre-resolved `attestations` list for whoever assembles
 * it; this panel seeds its checklist from that and then grows it locally as
 * THIS viewer signs steps in THIS session. A page reload will not show a
 * step someone else signed, or one signed earlier in a different session,
 * until a future task adds a real list endpoint. Disclosed, not hidden.
 *
 * ERRORS: every mutating action here reads `result.payload`, never
 * `result.error.message` — RTK's default serializer drops
 * `response.data.detail`, where the server's reason lives (e.g. "Every
 * required step must be signed before teardown. Still missing: ...").
 */
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';

import type { AppDispatch } from '../../store';
import {
  cancelDecommission,
  decideExtension,
  requestExtension,
  signAttestation,
  tearDown,
} from '../../store/decommissionSlice';
import { userGroupService } from '../../services/userGroupService';
import type {
  Decommission,
  DecommissionState,
  DecommissionStep,
  RemainingBookingSummary,
} from '../../types/decommission';

/** One checklist entry as the panel renders it — see the file-top comment on
 * why this is not simply `Attestation` (that type carries a numeric
 * `signed_by`, not a name; rule: render entities by name, never `#N`). */
export interface SignedStepView {
  step_key: string;
  signed_by_username: string;
  signed_at: string;
  reference?: string | null;
}

/** `Decommission` plus the extras a caller MAY already have resolved. Every
 * extra is optional — the plain `GET /environments/{id}/decommission`
 * response satisfies this type with none of them present. */
export interface DecommissionWithChecklist extends Decommission {
  initiated_by_username?: string | null;
  attestations?: SignedStepView[];
  remaining_bookings?: RemainingBookingSummary[];
}

export interface DecommissionPanelUser {
  id: number;
  username: string;
  role: string;
  is_master_admin: boolean;
}

export interface DecommissionPanelEnvironment {
  id: number;
  name: string;
  owner_user_id: number | null;
  operations_group_id: number | null;
}

interface DecommissionPanelProps {
  decommission: DecommissionWithChecklist;
  steps: DecommissionStep[];
  env: DecommissionPanelEnvironment;
  currentUser?: DecommissionPanelUser | null;
}

// Same five literals as EnvironmentList's DECOMMISSION_STATE_LABELS/COLORS
// (backend/app/core/decommission_states.py) — duplicated rather than
// imported to keep this panel's only coupling to that page one type, not one
// module.
const STATE_LABELS: Record<DecommissionState, string> = {
  warned: 'Warned',
  due: 'Due',
  extension_requested: 'Extension requested',
  torn_down: 'Torn down',
  cancelled: 'Cancelled',
};

const STATE_COLORS: Record<DecommissionState, 'warning' | 'error' | 'info' | 'default'> = {
  warned: 'warning',
  due: 'error',
  extension_requested: 'info',
  torn_down: 'default',
  cancelled: 'default',
};

const UTC_MONTHS = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/** "23 Aug 2026" — a fixed, locale-independent day, always read in UTC (this
 * app's dates are written at `T00:00:00Z`; see CLAUDE.md's day-arithmetic
 * pitfalls). A manual month table rather than `toLocaleDateString`: ICU's
 * `en-GB` short form renders September as "Sept", not "Sep", and that varies
 * by ICU data version — this must render identically everywhere. */
function formatUtcDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getUTCDate()} ${UTC_MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
}

export default function DecommissionPanel({
  decommission,
  steps,
  env,
  currentUser,
}: DecommissionPanelProps) {
  const dispatch = useDispatch<AppDispatch>();

  const isAdmin = currentUser?.role === 'Admin' || currentUser?.is_master_admin === true;
  const isOwner =
    currentUser != null && env.owner_user_id != null && currentUser.id === env.owner_user_id;

  // Mirrors HandoverSection's own membership lookup — see that file's
  // docstring for why this cannot be computed locally.
  const [inOperatingTeam, setInOperatingTeam] = useState(false);
  useEffect(() => {
    if (isAdmin) {
      setInOperatingTeam(false);
      return;
    }
    if (!env.operations_group_id || !currentUser) {
      setInOperatingTeam(false);
      return;
    }
    let cancelledEffect = false;
    userGroupService
      .listMembers(env.operations_group_id)
      .then((res) => {
        if (!cancelledEffect) {
          setInOperatingTeam(res.rows.some((m) => m.user_id === currentUser.id));
        }
      })
      .catch(() => {
        if (!cancelledEffect) setInOperatingTeam(false);
      });
    return () => {
      cancelledEffect = true;
    };
  }, [env.operations_group_id, isAdmin, currentUser]);

  const canRun = isAdmin || inOperatingTeam;
  const canDefend = isAdmin || isOwner;

  // The checklist. Re-seeded whenever a DIFFERENT decommission (or a fresh
  // `attestations` array from the caller) arrives — never on every render,
  // or a step signed locally this session would be wiped by the next
  // parent re-render carrying the same unchanged prop.
  const [signedSteps, setSignedSteps] = useState<SignedStepView[]>(
    decommission.attestations ?? []
  );
  useEffect(() => {
    setSignedSteps(decommission.attestations ?? []);
  }, [decommission.id, decommission.attestations]);

  const [error, setError] = useState<string | null>(null);
  const [referenceDrafts, setReferenceDrafts] = useState<Record<string, string>>({});
  const [signing, setSigning] = useState<string | null>(null);
  const [tearingDown, setTearingDown] = useState(false);
  const [deciding, setDeciding] = useState(false);

  const [extensionOpen, setExtensionOpen] = useState(false);
  const [extensionReason, setExtensionReason] = useState('');
  const [extensionUntil, setExtensionUntil] = useState('');
  const [extensionSubmitting, setExtensionSubmitting] = useState(false);

  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  const [cancelSubmitting, setCancelSubmitting] = useState(false);

  const isLive = !decommission.cancelled_at && !decommission.torn_down_at;
  const activeSteps = steps.filter((s) => s.is_active);
  const signedKeys = new Set(signedSteps.map((a) => a.step_key));
  const missingRequired = activeSteps.filter((s) => s.is_required && !signedKeys.has(s.key));

  const hasOpenExtensionRequest =
    decommission.extension_requested_at != null && decommission.extension_decided_at == null;
  // ONE extension per decommission (the server's own rule) — once a request
  // exists at all, granted or refused, the control never reappears.
  const canRequestExtension = canDefend && isLive && decommission.extension_requested_at == null;

  const remainingBookings = decommission.remaining_bookings ?? [];

  async function handleSign(stepKey: string) {
    setError(null);
    setSigning(stepKey);
    const result = await dispatch(
      signAttestation({
        decommissionId: decommission.id,
        data: { step_key: stepKey, reference: referenceDrafts[stepKey] || null },
      })
    );
    setSigning(null);
    if (signAttestation.rejected.match(result)) {
      setError(result.payload ?? 'Failed to sign this step');
      return;
    }
    setSignedSteps((prev) => [
      ...prev,
      {
        step_key: stepKey,
        signed_by_username: currentUser?.username ?? 'you',
        signed_at: new Date().toISOString(),
        reference: referenceDrafts[stepKey] || null,
      },
    ]);
    setReferenceDrafts((prev) => ({ ...prev, [stepKey]: '' }));
  }

  async function handleTearDown() {
    setError(null);
    setTearingDown(true);
    const result = await dispatch(tearDown(decommission.id));
    setTearingDown(false);
    if (tearDown.rejected.match(result)) {
      setError(result.payload ?? 'Failed to tear down this environment');
    }
  }

  async function handleDecideExtension(granted: boolean) {
    setError(null);
    setDeciding(true);
    const result = await dispatch(
      decideExtension({ decommissionId: decommission.id, data: { granted } })
    );
    setDeciding(false);
    if (decideExtension.rejected.match(result)) {
      setError(result.payload ?? 'Failed to record the extension decision');
    }
  }

  async function handleRequestExtension() {
    setError(null);
    setExtensionSubmitting(true);
    const result = await dispatch(
      requestExtension({
        decommissionId: decommission.id,
        data: { reason: extensionReason, until: extensionUntil },
      })
    );
    setExtensionSubmitting(false);
    if (requestExtension.rejected.match(result)) {
      setError(result.payload ?? 'Failed to request an extension');
      return;
    }
    setExtensionOpen(false);
    setExtensionReason('');
    setExtensionUntil('');
  }

  async function handleCancel() {
    setError(null);
    setCancelSubmitting(true);
    const result = await dispatch(
      cancelDecommission({ decommissionId: decommission.id, data: { reason: cancelReason } })
    );
    setCancelSubmitting(false);
    if (cancelDecommission.rejected.match(result)) {
      setError(result.payload ?? 'Failed to cancel this decommission');
      return;
    }
    setCancelOpen(false);
    setCancelReason('');
  }

  return (
    <Paper sx={{ p: 3 }} data-testid="decommission-panel">
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="h6">Decommission</Typography>
        <Chip
          size="small"
          label={STATE_LABELS[decommission.state]}
          color={STATE_COLORS[decommission.state]}
        />
      </Box>

      <Typography variant="body2" sx={{ mb: 0.5 }}>
        {decommission.reason}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        Scheduled teardown: {formatUtcDate(decommission.scheduled_teardown_at)}
      </Typography>
      {/* Never a bare `#N` fallback — omitted entirely when the caller has
          not resolved a name, which is the ordinary case today (see the
          file-top comment). */}
      {decommission.initiated_by_username && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
          Initiated by {decommission.initiated_by_username}
        </Typography>
      )}
      {decommission.cancelled_at && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
          Cancelled: {decommission.cancel_reason}
        </Typography>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 1, mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Divider sx={{ my: 2 }} />

      {/* Extension */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Extension
        </Typography>
        {hasOpenExtensionRequest && (
          <Alert severity="info" sx={{ mb: 1 }}>
            An extension has been requested — {decommission.extension_reason}, until{' '}
            {decommission.extension_until ? formatUtcDate(decommission.extension_until) : '—'}.
          </Alert>
        )}
        {!hasOpenExtensionRequest &&
          decommission.extension_decided_at != null && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Extension {decommission.extension_granted ? 'granted' : 'refused'} on{' '}
              {formatUtcDate(decommission.extension_decided_at)}.
            </Typography>
          )}
        <Stack direction="row" spacing={1}>
          {canRequestExtension && (
            <Button size="small" variant="outlined" onClick={() => setExtensionOpen(true)}>
              Request extension
            </Button>
          )}
          {hasOpenExtensionRequest && canRun && (
            <>
              <Button
                size="small"
                variant="contained"
                disabled={deciding}
                onClick={() => handleDecideExtension(true)}
              >
                Grant extension
              </Button>
              <Button
                size="small"
                variant="outlined"
                disabled={deciding}
                onClick={() => handleDecideExtension(false)}
              >
                Refuse extension
              </Button>
            </>
          )}
        </Stack>
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Checklist */}
      <Box sx={{ mb: 2 }}>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          Checklist
        </Typography>
        <Stack spacing={1.5}>
          {activeSteps.map((step) => {
            const signedEntry = signedSteps.find((a) => a.step_key === step.key);
            return (
              <Box key={step.key}>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography variant="body2">{step.label}</Typography>
                  {step.is_required && <Chip size="small" label="Required" />}
                </Stack>
                {signedEntry ? (
                  <Typography variant="body2" color="text.secondary">
                    Signed by {signedEntry.signed_by_username} on{' '}
                    {formatUtcDate(signedEntry.signed_at)}
                    {signedEntry.reference ? ` · ${signedEntry.reference}` : ''}
                  </Typography>
                ) : (
                  canRun &&
                  isLive && (
                    <Stack direction="row" spacing={1} sx={{ mt: 0.5 }}>
                      <TextField
                        size="small"
                        label="Reference"
                        value={referenceDrafts[step.key] ?? ''}
                        onChange={(e) =>
                          setReferenceDrafts((prev) => ({ ...prev, [step.key]: e.target.value }))
                        }
                      />
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={signing === step.key}
                        onClick={() => handleSign(step.key)}
                      >
                        Sign
                      </Button>
                    </Stack>
                  )
                )}
              </Box>
            );
          })}
        </Stack>
      </Box>

      <Divider sx={{ my: 2 }} />

      {/* Remaining bookings — SURFACES, never touches. B5 acts only where it
          says: no control here may change a booking. See the file-top
          comment and tests/test_b5_acts_only_where_it_says.py's UI half. */}
      {remainingBookings.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Bookings not touched by teardown
          </Typography>
          <Stack spacing={0.5}>
            {remainingBookings.map((b) => (
              <Typography key={b.id} variant="body2" color="text.secondary">
                {b.status} booking, {formatUtcDate(b.start_date)} – {formatUtcDate(b.end_date)}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}

      {/* Run actions */}
      {canRun && isLive && (
        <Stack direction="row" spacing={1} sx={{ mb: 1 }}>
          <Box>
            <Button
              variant="contained"
              color="error"
              disabled={missingRequired.length > 0 || tearingDown}
              onClick={handleTearDown}
            >
              Tear down
            </Button>
            {missingRequired.length > 0 && (
              <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                Sign every required step before tearing down:{' '}
                {missingRequired.map((s) => s.key).join(', ')}
              </Typography>
            )}
          </Box>
        </Stack>
      )}
      {canRun && !decommission.cancelled_at && (
        <Button size="small" onClick={() => setCancelOpen(true)}>
          Cancel decommission
        </Button>
      )}

      {/* Extension request dialog */}
      <Dialog open={extensionOpen} onClose={() => setExtensionOpen(false)}>
        <DialogTitle>Request an extension</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1, minWidth: 320 }}>
            <TextField
              label="Reason"
              value={extensionReason}
              onChange={(e) => setExtensionReason(e.target.value)}
              multiline
              minRows={2}
              fullWidth
            />
            <TextField
              label="Until"
              type="date"
              value={extensionUntil.slice(0, 10)}
              onChange={(e) => setExtensionUntil(`${e.target.value}T00:00:00Z`)}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setExtensionOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!extensionReason.trim() || !extensionUntil || extensionSubmitting}
            onClick={handleRequestExtension}
          >
            Submit request
          </Button>
        </DialogActions>
      </Dialog>

      {/* Cancel decommission dialog — CancelRequest.reason is required
          server-side (min_length=1), so this is never a single click. */}
      <Dialog open={cancelOpen} onClose={() => setCancelOpen(false)}>
        <DialogTitle>Cancel this decommission</DialogTitle>
        <DialogContent>
          <TextField
            label="Reason"
            value={cancelReason}
            onChange={(e) => setCancelReason(e.target.value)}
            multiline
            minRows={2}
            fullWidth
            sx={{ mt: 1, minWidth: 320 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCancelOpen(false)}>Back</Button>
          <Button
            variant="contained"
            color="error"
            disabled={!cancelReason.trim() || cancelSubmitting}
            onClick={handleCancel}
          >
            Confirm cancellation
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
}
