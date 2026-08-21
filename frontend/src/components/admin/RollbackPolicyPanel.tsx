/**
 * RollbackPolicyPanel — the per-tenant rollback policy (Phase 9 C4, task 7's
 * GET/PUT /tenant/rollback-policy), modelled on EnvironmentLifecyclePanel's
 * toggle-plus-save shape.
 *
 * THIS COPY MUST NOT LIE. Enabling a requirement here converts a warning
 * into a BLOCKER in the readiness VERDICT — it does not stop a deployment, a
 * release transition or a rollback; nothing in this product enforces
 * anything on the strength of it. See ReadinessBanner ("advisory only") and
 * backend/tests/test_c4_records_never_refuses.py /
 * test_c*_advises_never_blocks.py for the guard this panel must not
 * contradict.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Alert, Box, Button, FormControlLabel, Switch, TextField, Typography } from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchRollbackPolicy, updateRollbackPolicy } from '../../store/rollbackSlice';

export default function RollbackPolicyPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { policy, policyLoading, policyError } = useSelector((s: RootState) => s.rollback);

  // GET /tenant/rollback-policy is open to any tenant member; only PUT is
  // Admin-gated (see app/api/v1/rollback_policy.py — deliberately unlike
  // /tenant/users, which really is admin-gated throughout). Same split as
  // EnvironmentLifecyclePanel and EnvironmentNamingPolicyPanel: show, don't
  // hide, for a non-admin.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [requirePlan, setRequirePlan] = useState(false);
  const [requireRehearsal, setRequireRehearsal] = useState(false);
  const [validityDays, setValidityDays] = useState(90);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    dispatch(fetchRollbackPolicy());
  }, [dispatch]);

  // Seeded from the policy whenever it arrives or is re-saved — the form is
  // the draft, the store holds what the server last confirmed.
  useEffect(() => {
    if (!policy) return;
    setRequirePlan(policy.require_rollback_plan);
    setRequireRehearsal(policy.require_current_rehearsal);
    setValidityDays(policy.rehearsal_validity_days);
  }, [policy]);

  const handleSave = async () => {
    setSaved(false);
    const result = await dispatch(
      updateRollbackPolicy({
        require_rollback_plan: requirePlan,
        require_current_rehearsal: requireRehearsal,
        rehearsal_validity_days: validityDays,
      })
    );
    if (updateRollbackPolicy.fulfilled.match(result)) setSaved(true);
    // On rejection the slice holds formatApiError's text, read via
    // policyError below — never result.error.message, which for a real
    // AxiosError is the generic "Request failed with status code N".
  };

  return (
    <Box sx={{ mb: 4 }}>
      <Typography variant="h6" gutterBottom>
        Rollback Policy
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Decide whether a missing rollback plan or a missing/stale rehearsal is a
        <strong> warning</strong> or a <strong>blocker</strong> in a release's readiness verdict. This
        is advisory configuration only: neither setting stops a deployment, a release
        transition, or a rollback itself — a rollback can always be recorded (see Rollback
        History on a release) whether or not a plan exists at all, and nothing here is
        enforced by this product.
      </Typography>

      {!canWrite && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You can view this policy. Changing it requires an Admin.
        </Alert>
      )}
      {policyError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {policyError}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          Policy saved.
        </Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 720 }}>
        <FormControlLabel
          control={
            <Switch
              checked={requirePlan}
              onChange={(e) => setRequirePlan(e.target.checked)}
              disabled={policyLoading || !canWrite}
              inputProps={{ 'aria-label': 'Require a rollback plan' }}
            />
          }
          label="Require a rollback plan"
        />
        <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
          On: a changing component with no agreed rollback plan becomes a BLOCKER in the
          readiness verdict instead of a warning. Off (default): it's a warning only. Either
          way, nothing here refuses the release transition, the deployment, or a rollback.
        </Typography>

        <FormControlLabel
          control={
            <Switch
              checked={requireRehearsal}
              onChange={(e) => setRequireRehearsal(e.target.checked)}
              disabled={policyLoading || !canWrite}
              inputProps={{ 'aria-label': 'Require a current rehearsal' }}
            />
          }
          label="Require a current rehearsal"
        />
        <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
          On: a changing component whose system has no CURRENT passed rehearsal (missing,
          stale, or its most recent attempt failed) becomes a BLOCKER instead of a warning.
          Off (default): it's a warning only. Same rule — advisory only, blocks nothing.
        </Typography>

        <TextField
          label="Rehearsal validity period (days)"
          type="number"
          value={validityDays}
          onChange={(e) => setValidityDays(Number(e.target.value))}
          disabled={policyLoading || !canWrite}
          inputProps={{ min: 1, max: 3650 }}
          helperText="How long a passed rehearsal counts as current before it goes stale."
        />

        {canWrite && (
          <Box>
            <Button variant="contained" onClick={handleSave} disabled={policyLoading}>
              Save
            </Button>
          </Box>
        )}
      </Box>
    </Box>
  );
}
