import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchLifecyclePolicy,
  saveLifecyclePolicy,
} from '../../store/environmentLifecyclePolicySlice';
import {
  fetchAllDecommissionSteps,
  createDecommissionStep,
  updateDecommissionStep,
  deleteDecommissionStep,
} from '../../store/decommissionSlice';
import type { DecommissionStep, DecommissionStepWrite } from '../../types/decommission';

const EMPTY_STEP_FORM: DecommissionStepWrite = {
  key: '',
  label: '',
  description: '',
  display_order: 0,
  is_required: true,
  is_active: true,
};

export default function EnvironmentLifecyclePanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { policy, loading, error } = useSelector(
    (s: RootState) => s.environmentLifecyclePolicy
  );
  const { adminSteps, adminStepsLoading, adminStepsError } = useSelector(
    (s: RootState) => s.decommission
  );

  // The backend gates PUT /tenant/environment-lifecycle-policy and every
  // /tenant/decommission-steps write on require_tenant_admin(); GET is open
  // to any tenant member. Mirror that split here rather than hiding the
  // panel for a non-admin — same call UserGroups.tsx makes, and the false
  // analogy with /tenant/users (which really is admin-gated throughout) is
  // exactly what got this wrong on B3a's first pass.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [idleEnabled, setIdleEnabled] = useState(false);
  const [idleThresholdDays, setIdleThresholdDays] = useState(30);
  const [noticeDays, setNoticeDays] = useState(5);
  const [saved, setSaved] = useState(false);

  const [stepDialogOpen, setStepDialogOpen] = useState(false);
  const [stepForm, setStepForm] = useState<DecommissionStepWrite>(EMPTY_STEP_FORM);
  const [editingStepId, setEditingStepId] = useState<number | null>(null);
  const [stepFormError, setStepFormError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<DecommissionStep | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchLifecyclePolicy());
    dispatch(fetchAllDecommissionSteps());
  }, [dispatch]);

  // Seeded from the policy in force whenever it arrives or is re-saved — the
  // form is the draft, the store holds what the server last confirmed. This
  // fires even for a tenant that has never saved a policy: get_policy answers
  // an UNSAVED default instance (disabled, 30/5) rather than 404ing, so there
  // is always a value to seed from, never an error state to special-case.
  useEffect(() => {
    if (!policy) return;
    setIdleEnabled(policy.idle_detection_enabled);
    setIdleThresholdDays(policy.idle_threshold_days);
    setNoticeDays(policy.decommission_notice_days);
  }, [policy]);

  const handleSave = async () => {
    setSaved(false);
    // Built explicitly, never spread from `policy` — the read model and the
    // update model happen to share this exact key set today, but a field
    // added to one side later must not silently leak into the other the way
    // B2's naming policy did with `effective_from`.
    const result = await dispatch(
      saveLifecyclePolicy({
        idle_detection_enabled: idleEnabled,
        idle_threshold_days: idleThresholdDays,
        decommission_notice_days: noticeDays,
      })
    );
    if (saveLifecyclePolicy.fulfilled.match(result)) setSaved(true);
    // On rejection the slice holds formatApiError's text — reading
    // result.error.message here would render "Request failed with status
    // code 422" instead of the server's actual constraint.
  };

  const openCreateStep = () => {
    setEditingStepId(null);
    setStepForm(EMPTY_STEP_FORM);
    setStepFormError(null);
    setStepDialogOpen(true);
  };

  const openEditStep = (step: DecommissionStep) => {
    setEditingStepId(step.id);
    setStepForm({
      key: step.key,
      label: step.label,
      description: step.description ?? '',
      display_order: step.display_order,
      is_required: step.is_required,
      is_active: step.is_active,
    });
    setStepFormError(null);
    setStepDialogOpen(true);
  };

  const handleStepSave = async () => {
    if (!stepForm.key.trim() || !stepForm.label.trim()) return;
    setStepFormError(null);
    // PATCH takes the same DecommissionStepWrite shape as POST — every
    // field travels on every edit, there is no partial-update schema.
    const body: DecommissionStepWrite = {
      key: stepForm.key.trim(),
      label: stepForm.label.trim(),
      description: stepForm.description?.trim() ? stepForm.description.trim() : null,
      display_order: stepForm.display_order ?? 0,
      is_required: stepForm.is_required ?? true,
      is_active: stepForm.is_active ?? true,
    };
    const result =
      editingStepId === null
        ? await dispatch(createDecommissionStep(body))
        : await dispatch(updateDecommissionStep({ id: editingStepId, data: body }));
    if (
      createDecommissionStep.rejected.match(result) ||
      updateDecommissionStep.rejected.match(result)
    ) {
      setStepFormError(result.payload ?? 'Failed to save this step');
      return;
    }
    setStepDialogOpen(false);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    const result = await dispatch(deleteDecommissionStep(deleteTarget.id));
    if (deleteDecommissionStep.rejected.match(result)) {
      setDeleteError(result.payload ?? 'Failed to retire this step');
      return;
    }
    setDeleteTarget(null);
  };

  const columns: GridColDef<DecommissionStep>[] = [
    { field: 'label', headerName: 'Step', flex: 1 },
    { field: 'key', headerName: 'Key', width: 160 },
    { field: 'display_order', headerName: 'Order', width: 90 },
    {
      field: 'is_required',
      headerName: 'Required',
      width: 100,
      renderCell: (params) => (params.row.is_required ? 'Required' : 'Optional'),
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 100,
      renderCell: (params) => (params.row.is_active ? 'Active' : 'Retired'),
    },
    {
      field: 'actions',
      headerName: '',
      width: 160,
      sortable: false,
      renderCell: (params) =>
        canWrite ? (
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            <Button size="small" onClick={() => openEditStep(params.row)}>
              Edit
            </Button>
            <Button size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
              Delete
            </Button>
          </Box>
        ) : null,
    },
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <Typography variant="h6" gutterBottom>
        Environment Lifecycle &amp; Decommissioning
      </Typography>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        Configure idle detection, the notice period before a scheduled teardown, and the
        checklist a decommission is gated on.
      </Typography>

      {!canWrite && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You can view these settings. Changing them requires an Admin.
        </Alert>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSaved(false)}>
          Policy saved.
        </Alert>
      )}

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, maxWidth: 720, mb: 4 }}>
        <FormControlLabel
          control={
            <Switch
              checked={idleEnabled}
              onChange={(e) => setIdleEnabled(e.target.checked)}
              disabled={loading || !canWrite}
              inputProps={{ 'aria-label': 'Idle detection enabled' }}
            />
          }
          label="Idle detection enabled"
        />
        {/* Off by default, and turning it on is estate-wide and immediate —
            same shape as B2's `?governance_gap=true` matching every existing
            environment on first deploy. Said here rather than discovered as
            a wall of new chips. */}
        <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
          Enabling this immediately flags every environment already quiet longer than the
          threshold below across the whole estate — not just ones booked from now on.
        </Typography>

        <TextField
          label="Idle threshold (days)"
          type="number"
          value={idleThresholdDays}
          onChange={(e) => setIdleThresholdDays(Number(e.target.value))}
          disabled={loading || !canWrite}
          inputProps={{ min: 1, max: 3650 }}
          helperText="How long an environment may go without a booking before it reads as idle. A tier can override this — see Environment Tiers."
        />

        <TextField
          label="Decommission notice period (days)"
          type="number"
          value={noticeDays}
          onChange={(e) => setNoticeDays(Number(e.target.value))}
          disabled={loading || !canWrite}
          inputProps={{ min: 1, max: 365 }}
          helperText="How much warning an owner gets before a scheduled teardown, by default. An initiator may push the date later, never earlier."
        />

        {canWrite && (
          <Box>
            <Button variant="contained" onClick={handleSave} disabled={loading}>
              Save
            </Button>
          </Box>
        )}
      </Box>

      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Decommission Checklist</Typography>
        {canWrite && (
          <Button variant="contained" size="small" onClick={openCreateStep}>
            + New Step
          </Button>
        )}
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        The steps a teardown checks off against. Retiring a step stops it gating future
        decommissions immediately — it does not remove or invalidate attestations already
        signed against it.
      </Typography>
      {adminStepsError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {adminStepsError}
        </Alert>
      )}

      <DataTable
        storageKey="admin-environment-lifecycle-steps"
        emptyMessage="No lifecycle steps configured yet."
        rows={adminSteps}
        columns={columns}
        loading={adminStepsLoading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog
        open={stepDialogOpen}
        onClose={() => setStepDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{editingStepId === null ? 'New Decommission Step' : 'Edit Decommission Step'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {stepFormError && <Alert severity="error">{stepFormError}</Alert>}
          <TextField
            label="Key"
            required
            value={stepForm.key}
            onChange={(e) => setStepForm({ ...stepForm, key: e.target.value })}
            helperText="Stable identifier — attestations reference this even after the step is retired or its label changes."
          />
          <TextField
            label="Label"
            required
            value={stepForm.label}
            onChange={(e) => setStepForm({ ...stepForm, label: e.target.value })}
          />
          <TextField
            label="Description"
            multiline
            minRows={2}
            value={stepForm.description ?? ''}
            onChange={(e) => setStepForm({ ...stepForm, description: e.target.value })}
          />
          <TextField
            label="Display order"
            type="number"
            value={stepForm.display_order ?? 0}
            onChange={(e) =>
              setStepForm({ ...stepForm, display_order: Number(e.target.value) })
            }
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={stepForm.is_required ?? true}
                onChange={(e) => setStepForm({ ...stepForm, is_required: e.target.checked })}
              />
            }
            label="Required — a teardown is refused until this is signed"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={stepForm.is_active ?? true}
                onChange={(e) => setStepForm({ ...stepForm, is_active: e.target.checked })}
              />
            }
            label="Active"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStepDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleStepSave}
            disabled={!stepForm.key.trim() || !stepForm.label.trim()}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Retire Decommission Step</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          {/* Deliberately no data-loss language: this is a soft delete that
              is never refused, and attestations keep step_key as a plain
              string so signed records go on reading correctly. */}
          <Typography>
            Retire <strong>{deleteTarget?.label}</strong>? It will stop gating new
            decommissions. Already-signed attestations for it are unaffected.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Retire
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
