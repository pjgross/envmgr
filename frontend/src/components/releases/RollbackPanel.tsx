/**
 * RollbackPanel — Phase 9 C4's rollback tab on the release detail page.
 *
 * Renders the release-level reversibility rollup, one row per CHANGING
 * component (role 'changing' or 'config_only' — a 'regression' component has
 * nothing to roll back, the same exclusion release_readiness_service's
 * findings make), and the authorisation history below.
 *
 * C4 RECORDS; IT NEVER REFUSES. "Record a rollback" must stay enabled no
 * matter what plans exist or don't — see RecordRollbackDialog and
 * backend/tests/test_c4_records_never_refuses.py. Nothing on this panel
 * disables a control on the strength of plan or rehearsal state; that
 * distinction belongs to the readiness verdict (ReadinessBanner), which
 * needs no change here — it already renders whatever the verdict returns.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchRollbackPlans,
  fetchRollbackAuthorisations,
  agreeRollbackPlan,
  deleteRollbackPlan,
} from '../../store/rollbackSlice';
import { releaseService } from '../../services/releaseService';
import { formatApiError } from '../../services/apiError';
import { formatBookingDateTime } from '../../utils/datetime';
import { useConfirm } from '../../hooks/useConfirm';
import type { ReleaseSystemResponse } from '../../types/release';
import type { ReleaseReadinessResponse } from '../../types/gateReadiness';
import type { RollbackPlanResponse } from '../../types/rollback';
import RollbackPlanDialog from './RollbackPlanDialog';
import RecordRollbackDialog from './RecordRollbackDialog';

interface Props {
  releaseId: number;
}

const REVERSIBILITY_COLOR: Record<string, 'success' | 'warning' | 'error'> = {
  reversible: 'success',
  lossy: 'warning',
  irreversible: 'error',
};

const REVERSIBILITY_LABEL: Record<string, string> = {
  reversible: 'Reversible',
  lossy: 'Lossy',
  irreversible: 'Irreversible',
};

export default function RollbackPanel({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { plans, plansLoading, plansError, authorisations, authorisationsError } =
    useSelector((s: RootState) => s.rollback);
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [systems, setSystems] = useState<ReleaseSystemResponse[]>([]);
  const [systemsError, setSystemsError] = useState<string | null>(null);

  // Findings 1+2: this used to be computed client-side (`rollupReversibility`
  // over `visiblePlans`, filtered to changing/config_only components) — a
  // SECOND computation of the same value the backend already ships on
  // `readiness.reversibility`, and the backend's own field had ZERO
  // consumers anywhere in the frontend. Removing a component from a release
  // (DELETE /release-systems/{id}, an ordinary UI action) hard-deletes the
  // release_system row but leaves its rollback plan live, so the two
  // computations could disagree about whether the release was irreversible
  // — the single-verdict guarantee broken by a plain UI action, not just a
  // hand-crafted API call. There is now exactly ONE computation, on the
  // server, on the route a pipeline obeys (GET /webhooks/release-ready calls
  // the same release_readiness_service.evaluate()).
  const [readiness, setReadiness] = useState<ReleaseReadinessResponse | null>(null);

  // Bumped once per confirmed plan mutation (create, edit, agree, delete) —
  // never on every Redux `plans` reference change, which fires twice per
  // mutation (once on the thunk's pending, once on fulfilled) and would
  // still fire on the initial mount's own fetch. A readiness re-fetch is
  // wanted exactly once per mutation that actually landed server-side, so
  // this is bumped from the handlers below and from RollbackPlanDialog's
  // onSaved callback — never from an effect watching `plans` itself, which
  // would tie this fetch's cadence to that state's own churn rather than to
  // "a mutation happened".
  const [refreshKey, setRefreshKey] = useState(0);

  const [planDialogTarget, setPlanDialogTarget] = useState<{
    systemId: number;
    systemName: string | null;
    plan: RollbackPlanResponse | null;
  } | null>(null);
  const [recordOpen, setRecordOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchRollbackPlans(releaseId));
    dispatch(fetchRollbackAuthorisations(releaseId));
  }, [dispatch, releaseId]);

  useEffect(() => {
    let cancelled = false;
    setReadiness(null);
    releaseService
      .getReadiness(releaseId)
      .then((r) => {
        if (!cancelled) setReadiness(r);
      })
      .catch(() => {
        // Same rule as ReadinessBanner: a failed readiness check must not
        // block rendering the rest of the panel.
        if (!cancelled) setReadiness(null);
      });
    return () => {
      cancelled = true;
    };
  }, [releaseId, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    setSystems([]);
    setSystemsError(null);
    releaseService
      .listSystems(releaseId)
      .then((rows) => {
        if (!cancelled) setSystems(rows);
      })
      .catch((err) => {
        if (!cancelled) setSystemsError(formatApiError(err, 'Failed to load this release’s systems'));
      });
    return () => {
      cancelled = true;
    };
  }, [releaseId]);

  const changingComponents = useMemo(
    () => systems.filter((s) => s.role === 'changing' || s.role === 'config_only'),
    [systems]
  );

  const planBySystemId = useMemo(() => {
    const map = new Map<number, RollbackPlanResponse>();
    for (const p of plans) map.set(p.system_id, p);
    return map;
  }, [plans]);

  const allSystemOptions = useMemo(
    () => systems.map((s) => ({ id: s.system_id, name: s.system_name ?? `#${s.system_id}` })),
    [systems]
  );

  // The backend's own answer, not a re-derivation of it. `readiness` is null
  // until the fetch resolves (or if it fails) — render the "no plans"
  // treatment rather than claiming a verdict nobody has confirmed yet.
  const rollup = readiness?.reversibility ?? null;

  const handleAgree = async (plan: RollbackPlanResponse) => {
    setActionError(null);
    const result = await dispatch(agreeRollbackPlan({ releaseId, planId: plan.id }));
    if (agreeRollbackPlan.rejected.match(result)) {
      setActionError(result.payload ?? 'Failed to record agreement');
      return;
    }
    // Agreement doesn't change a plan's reversibility, but it is still a
    // plan mutation the readiness verdict may care about (e.g. a policy
    // that treats an unagreed plan as equivalent to no plan at all) — so it
    // refreshes the same way create/edit/delete do.
    setRefreshKey((k) => k + 1);
  };

  const handleDelete = async (plan: RollbackPlanResponse) => {
    const ok = await confirm({
      title: 'Delete Rollback Plan',
      message: `Delete the rollback plan for ${plan.system_name ?? 'this component'}? This does not affect any recorded rollback history.`,
      destructive: true,
      confirmLabel: 'Delete',
    });
    if (!ok) return;
    setActionError(null);
    const result = await dispatch(deleteRollbackPlan({ releaseId, planId: plan.id }));
    if (deleteRollbackPlan.rejected.match(result)) {
      setActionError(result.payload ?? 'Failed to delete the rollback plan');
      return;
    }
    setRefreshKey((k) => k + 1);
  };

  return (
    <Box>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
        <Chip
          label={
            rollup
              ? `Rollback readiness: ${REVERSIBILITY_LABEL[rollup] ?? rollup}`
              : 'No rollback plans yet'
          }
          color={rollup ? REVERSIBILITY_COLOR[rollup] : 'default'}
          variant={rollup ? 'filled' : 'outlined'}
        />
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" onClick={() => setRecordOpen(true)}>
          Record a rollback
        </Button>
      </Stack>

      {plansError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {plansError}
        </Alert>
      )}
      {systemsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {systemsError}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <Typography variant="h6" gutterBottom>
        Rollback Plans
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        One plan per changing component. A plan is advisory — see the tenant's Rollback
        Policy for whether a missing plan or rehearsal is a warning or a blocker in the
        readiness verdict.
      </Typography>

      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Component</TableCell>
              <TableCell>Reversibility</TableCell>
              <TableCell>Est. time</TableCell>
              <TableCell>Steps</TableCell>
              <TableCell>Agreement</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {changingComponents.map((c) => {
              const plan = planBySystemId.get(c.system_id) ?? null;
              return (
                <TableRow key={c.id}>
                  <TableCell>{c.system_name ?? `#${c.system_id}`}</TableCell>
                  <TableCell>
                    {plan ? (
                      <Chip
                        size="small"
                        label={REVERSIBILITY_LABEL[plan.reversibility] ?? plan.reversibility}
                        color={REVERSIBILITY_COLOR[plan.reversibility]}
                      />
                    ) : (
                      <Chip size="small" label="No plan" variant="outlined" />
                    )}
                  </TableCell>
                  <TableCell>
                    {plan?.estimated_minutes != null ? `${plan.estimated_minutes} min` : '—'}
                  </TableCell>
                  <TableCell sx={{ maxWidth: 320, whiteSpace: 'pre-wrap' }}>
                    {plan?.steps ?? '—'}
                  </TableCell>
                  <TableCell>
                    {plan?.agreed_by_username ? (
                      <Typography variant="body2">Agreed by {plan.agreed_by_username}</Typography>
                    ) : plan ? (
                      <Button size="small" onClick={() => handleAgree(plan)}>
                        Agree
                      </Button>
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        —
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Button
                      size="small"
                      onClick={() =>
                        setPlanDialogTarget({
                          systemId: c.system_id,
                          systemName: c.system_name,
                          plan,
                        })
                      }
                    >
                      {plan ? 'Edit' : 'Create plan'}
                    </Button>
                    {plan && (
                      <IconButton
                        size="small"
                        color="error"
                        aria-label={`Delete rollback plan for ${c.system_name ?? c.system_id}`}
                        onClick={() => handleDelete(plan)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {changingComponents.length === 0 && !plansLoading && (
              <TableRow>
                <TableCell colSpan={6}>
                  <Typography color="text.secondary">
                    This release has no changing components yet.
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="h6" sx={{ mt: 4 }} gutterBottom>
        Rollback History
      </Typography>
      {authorisationsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {authorisationsError}
        </Alert>
      )}
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>When</TableCell>
              <TableCell>Trigger</TableCell>
              <TableCell>Rationale</TableCell>
              <TableCell>Systems</TableCell>
              <TableCell>Recorded by</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {authorisations.map((a) => (
              <TableRow key={a.id}>
                <TableCell>{formatBookingDateTime(a.decided_at)}</TableCell>
                <TableCell>{a.trigger}</TableCell>
                <TableCell>{a.rationale}</TableCell>
                <TableCell>{a.system_names.join(', ') || '—'}</TableCell>
                <TableCell>{a.decided_by_username ?? '—'}</TableCell>
              </TableRow>
            ))}
            {authorisations.length === 0 && (
              <TableRow>
                <TableCell colSpan={5}>
                  <Typography color="text.secondary">No rollbacks recorded yet.</Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {planDialogTarget && (
        <RollbackPlanDialog
          releaseId={releaseId}
          systemId={planDialogTarget.systemId}
          systemName={planDialogTarget.systemName}
          plan={planDialogTarget.plan}
          open={Boolean(planDialogTarget)}
          onClose={() => setPlanDialogTarget(null)}
          onSaved={() => setRefreshKey((k) => k + 1)}
        />
      )}

      <RecordRollbackDialog
        releaseId={releaseId}
        open={recordOpen}
        onClose={() => setRecordOpen(false)}
        systems={allSystemOptions}
      />

      {confirmDialog}
    </Box>
  );
}
