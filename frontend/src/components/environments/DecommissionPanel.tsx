/**
 * DecommissionPanel — B5 Task 12 (+ the Task-12 review fix). The one surface
 * that drives the whole decommission workflow: the banner, every control the
 * viewer may actually use, the entry point that STARTS one, and the
 * attestation checklist, ALL TOGETHER in one panel.
 *
 * A2's `GroupTransitionPanel` lesson, restated for B5: a banner that
 * diagnoses a state and offers no way to act on it is where three tasks
 * quietly removed the repair affordance. Controls live next to the state
 * they act on — there is no separate "actions" section here.
 *
 * THE PRIMARY JOURNEY MUST BE REACHABLE FROM THE PRODUCT. B3b shipped a
 * workflow whose primary journey (submitting the request that starts it) was
 * impossible, caught only by tracing the journey — never by the diff or the
 * tests. This panel's first review shipped the same shape: `decommission`
 * was a required, non-null prop, so the panel only ever rendered once one
 * already existed, and nothing anywhere called `initiateDecommission`. Fixed
 * here: `decommission` is `| null`, and when it is null (or the most recent
 * record is no longer LIVE — cancelled or torn down, so a fresh one is
 * legal) the panel offers "Start decommission" to whoever is entitled to use
 * it.
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
 * ATTESTATION HISTORY. `GET /environments/{id}/decommission` now carries a
 * real `attestations` field (backend fix landed alongside this one — see
 * `DecommissionRead.attestations` / `list_attestations`), so the checklist
 * seeds from the real wire response, not a locally-invented one. It still
 * grows locally the moment THIS viewer signs a step in THIS session, ahead
 * of the next fetch, the same optimistic-update shape used everywhere else
 * in this codebase.
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
  initiateDecommission,
  requestExtension,
  signAttestation,
  tearDown,
} from '../../store/decommissionSlice';
import { userGroupService } from '../../services/userGroupService';
import type {
  Attestation,
  Decommission,
  DecommissionState,
  DecommissionStep,
  RemainingBookingSummary,
} from '../../types/decommission';

/**
 * One checklist entry as the panel RENDERS it — deliberately not the same
 * shape as the wire `Attestation` (which also carries `id`, `decommission_id`,
 * the numeric `signed_by`, and `notes`, none of which this panel displays).
 * `toSignedStepViews` below is the one place that narrows the wire shape
 * into this one; a step just signed in THIS session is appended directly in
 * this shape, ahead of the next fetch.
 *
 * `signed_by_username` is nullable, never a bare `#N`: the backend resolves
 * it via a LEFT JOIN (`list_attestations`) that can legitimately find no
 * matching `User` row, and the render below omits the name rather than
 * inventing one when that happens.
 */
export interface SignedStepView {
  step_key: string;
  signed_by_username: string | null;
  signed_at: string;
  reference?: string | null;
}

// `attestations` is REQUIRED on `Decommission` (never optional — see that
// type's own comment: an omitted field would render a signed step as
// unsigned, which is exactly the bug Finding 2 fixed). The parameter here is
// still `| undefined`, and the `?? []` below is still doing real work, for a
// DIFFERENT reason: this is always called as `toSignedStepViews(effective
// ?.attestations)`, and `effective` itself (the whole decommission) is
// legitimately `null` while no decommission exists yet — optional chaining
// on a null object produces `undefined` regardless of whether the field on
// the object type is required. Once `effective` is non-null, `.attestations`
// is always a real (possibly empty) array.
function toSignedStepViews(attestations: Attestation[] | undefined): SignedStepView[] {
  return (attestations ?? []).map((a) => ({
    step_key: a.step_key,
    signed_by_username: a.signed_by_username ?? null,
    signed_at: a.signed_at,
    reference: a.reference,
  }));
}

/** `Decommission` plus the extras a caller MAY already have resolved.
 * `attestations` (inherited from `Decommission`, real `Attestation[]` on the
 * wire) travels on the real `GET .../decommission` response now — see
 * `toSignedStepViews` above for how the panel narrows it to its own display
 * shape. `remaining_bookings` only arrives via a teardown response, so
 * `EnvironmentDetail` merges the slice's separately-tracked
 * `remainingBookings` onto it before handing this down. */
export interface DecommissionWithChecklist extends Decommission {
  initiated_by_username?: string | null;
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
  /** `null` when this environment has never been decommissioned — the
   * ordinary case `GET .../decommission` answers with, never a 404 (see
   * decommissions.py's own module docstring). The panel's "Start
   * decommission" control lives here, not on the parent page, per this
   * file's own top-of-file rule: controls sit next to the state they act
   * on. */
  decommission: DecommissionWithChecklist | null;
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

  // A decommission just started in THIS session, before the parent's own
  // fetch has caught up. `decommission` (the prop) always wins once the
  // parent re-supplies a real one — this is a bridge, not a cache. All
  // hooks below are called unconditionally regardless of whether either is
  // present, per the rules of hooks; the null/non-null branch happens only
  // in the JSX at the bottom.
  const [justInitiated, setJustInitiated] = useState<DecommissionWithChecklist | null>(null);
  const effective = decommission ?? justInitiated;

  // The checklist. Seeded from the real `attestations` field on `effective`
  // (see the file-top comment — this now travels on the wire) and re-seeded
  // whenever a DIFFERENT decommission (or a fresh `attestations` array from
  // the caller) arrives — never on every render, or a step signed locally
  // this session would be wiped by the next parent re-render carrying the
  // same unchanged prop.
  const [signedSteps, setSignedSteps] = useState<SignedStepView[]>(
    toSignedStepViews(effective?.attestations)
  );
  useEffect(() => {
    setSignedSteps(toSignedStepViews(effective?.attestations));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effective?.id, effective?.attestations]);

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

  const [initiateOpen, setInitiateOpen] = useState(false);
  const [initiateReason, setInitiateReason] = useState('');
  const [initiateTeardown, setInitiateTeardown] = useState('');
  const [initiateSubmitting, setInitiateSubmitting] = useState(false);

  const isLive = effective ? !effective.cancelled_at && !effective.torn_down_at : false;
  const activeSteps = steps.filter((s) => s.is_active);
  const signedKeys = new Set(signedSteps.map((a) => a.step_key));
  const missingRequired = activeSteps.filter((s) => s.is_required && !signedKeys.has(s.key));

  const hasOpenExtensionRequest =
    !!effective &&
    effective.extension_requested_at != null &&
    effective.extension_decided_at == null;
  // ONE extension per decommission (the server's own rule) — once a request
  // exists at all, granted or refused, the control never reappears.
  const canRequestExtension =
    !!effective && canDefend && isLive && effective.extension_requested_at == null;

  const remainingBookings = effective?.remaining_bookings ?? [];

  // A live decommission already exists (the server 409s a second one) — no
  // start control while that's true. Once `effective` is null, or the most
  // recent record is terminal (cancelled/torn down), starting a new one is
  // legal again.
  const canStartDecommission = canRun && !isLive;

  async function handleSign(stepKey: string) {
    if (!effective) return;
    setError(null);
    setSigning(stepKey);
    const result = await dispatch(
      signAttestation({
        decommissionId: effective.id,
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
    if (!effective) return;
    setError(null);
    setTearingDown(true);
    const result = await dispatch(tearDown(effective.id));
    setTearingDown(false);
    if (tearDown.rejected.match(result)) {
      setError(result.payload ?? 'Failed to tear down this environment');
    }
  }

  async function handleDecideExtension(granted: boolean) {
    if (!effective) return;
    setError(null);
    setDeciding(true);
    const result = await dispatch(
      decideExtension({ decommissionId: effective.id, data: { granted } })
    );
    setDeciding(false);
    if (decideExtension.rejected.match(result)) {
      setError(result.payload ?? 'Failed to record the extension decision');
    }
  }

  async function handleRequestExtension() {
    if (!effective) return;
    setError(null);
    setExtensionSubmitting(true);
    const result = await dispatch(
      requestExtension({
        decommissionId: effective.id,
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
    if (!effective) return;
    setError(null);
    setCancelSubmitting(true);
    const result = await dispatch(
      cancelDecommission({ decommissionId: effective.id, data: { reason: cancelReason } })
    );
    setCancelSubmitting(false);
    if (cancelDecommission.rejected.match(result)) {
      setError(result.payload ?? 'Failed to cancel this decommission');
      return;
    }
    setCancelOpen(false);
    setCancelReason('');
  }

  async function handleInitiate() {
    setError(null);
    setInitiateSubmitting(true);
    const result = await dispatch(
      initiateDecommission({
        environmentId: env.id,
        data: {
          reason: initiateReason,
          // Optional: the server computes the notice-period default when
          // omitted, and 422s an earlier one than that default allows — we
          // do not pre-validate that here (we don't know the tenant's
          // notice period client-side); the server's own message surfaces
          // through `result.payload` like every other refusal in this file.
          ...(initiateTeardown ? { scheduled_teardown_at: initiateTeardown } : {}),
        },
      })
    );
    setInitiateSubmitting(false);
    if (initiateDecommission.rejected.match(result)) {
      setError(result.payload ?? 'Failed to start this decommission');
      return;
    }
    setJustInitiated(result.payload);
    setInitiateOpen(false);
    setInitiateReason('');
    setInitiateTeardown('');
  }

  return (
    <Paper sx={{ p: 3 }} data-testid="decommission-panel">
      <Typography variant="h6" sx={{ mb: 1 }}>
        Decommission
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      {canStartDecommission && (
        <Box sx={{ mb: effective ? 2 : 0 }}>
          {!effective && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              This environment has no active decommission.
            </Typography>
          )}
          <Button variant="outlined" onClick={() => setInitiateOpen(true)}>
            Start decommission
          </Button>
        </Box>
      )}

      {effective && (
        <>
          <Box
            sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}
          >
            <Box />
            <Chip
              size="small"
              label={STATE_LABELS[effective.state]}
              color={STATE_COLORS[effective.state]}
            />
          </Box>

          <Typography variant="body2" sx={{ mb: 0.5 }}>
            {effective.reason}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
            Scheduled teardown: {formatUtcDate(effective.scheduled_teardown_at)}
          </Typography>
          {/* Never a bare `#N` fallback — omitted entirely when the caller
              has not resolved a name. */}
          {effective.initiated_by_username && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Initiated by {effective.initiated_by_username}
            </Typography>
          )}
          {effective.cancelled_at && (
            <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
              Cancelled: {effective.cancel_reason}
            </Typography>
          )}

          <Divider sx={{ my: 2 }} />

          {/* Extension */}
          <Box sx={{ mb: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Extension
            </Typography>
            {hasOpenExtensionRequest && (
              <Alert severity="info" sx={{ mb: 1 }}>
                An extension has been requested — {effective.extension_reason}, until{' '}
                {effective.extension_until ? formatUtcDate(effective.extension_until) : '—'}.
              </Alert>
            )}
            {!hasOpenExtensionRequest && effective.extension_decided_at != null && (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Extension {effective.extension_granted ? 'granted' : 'refused'} on{' '}
                {formatUtcDate(effective.extension_decided_at)}.
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
                        {signedEntry.signed_by_username
                          ? `Signed by ${signedEntry.signed_by_username} on `
                          : 'Signed on '}
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
                              setReferenceDrafts((prev) => ({
                                ...prev,
                                [step.key]: e.target.value,
                              }))
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

          {/* Remaining bookings — SURFACES, never touches. B5 acts only
              where it says: no control here may change a booking. See the
              file-top comment and tests/test_b5_acts_only_where_it_says.py's
              UI half. */}
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
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    display="block"
                    sx={{ mt: 0.5 }}
                  >
                    Sign every required step before tearing down:{' '}
                    {missingRequired.map((s) => s.key).join(', ')}
                  </Typography>
                )}
              </Box>
            </Stack>
          )}
          {canRun && !effective.cancelled_at && (
            <Button size="small" onClick={() => setCancelOpen(true)}>
              Cancel decommission
            </Button>
          )}
        </>
      )}

      {/* Start-decommission dialog */}
      <Dialog open={initiateOpen} onClose={() => setInitiateOpen(false)}>
        <DialogTitle>Start a decommission</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1, minWidth: 320 }}>
            <TextField
              label="Reason"
              value={initiateReason}
              onChange={(e) => setInitiateReason(e.target.value)}
              multiline
              minRows={2}
              fullWidth
            />
            <TextField
              label="Teardown date (optional — defaults to the notice period)"
              type="date"
              value={initiateTeardown.slice(0, 10)}
              onChange={(e) =>
                setInitiateTeardown(e.target.value ? `${e.target.value}T00:00:00Z` : '')
              }
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInitiateOpen(false)}>Back</Button>
          <Button
            variant="contained"
            disabled={!initiateReason.trim() || initiateSubmitting}
            onClick={handleInitiate}
          >
            Confirm start
          </Button>
        </DialogActions>
      </Dialog>

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
