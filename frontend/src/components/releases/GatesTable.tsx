/**
 * GatesTable — expandable list of release gates with per-gate criteria.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Chip,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import GavelIcon from '@mui/icons-material/Gavel';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import type { AppDispatch } from '../../store';
import {
  createGate,
  updateGate,
  deleteGate,
  fetchGates,
  createCriterion,
  updateCriterion,
  completeCriterion,
  reopenCriterion,
  deleteCriterion,
  fetchGateEvidence,
  deleteGateEvidence,
} from '../../store/releaseSlice';
import { fetchGateTypes, selectActiveGateTypes } from '../../store/gateTypeSlice';
import type { RootState } from '../../store';
import api from '../../services/api';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import GateDecisionDialog from './GateDecisionDialog';
import WaiverDialog from './WaiverDialog';
import WaiverChip from './WaiverChip';
import GateEvidenceList from './GateEvidenceList';
import AddEvidenceDialog from './AddEvidenceDialog';
import CriterionRow from './CriterionRow';
import CriterionDialog from './CriterionDialog';
import type { ReleaseGateResponse } from '../../types/release';
import type { GateCriterion, GateCriterionCreatePayload, GateCriterionUpdatePayload } from '../../types/gateCriterion';
import type { GateEvidenceResponse } from '../../types/gateEvidence';

interface Props {
  releaseId: number;
  gates: ReleaseGateResponse[];
  onRefresh: () => void;
}

const STATUS_COLORS: Record<
  string,
  'default' | 'success' | 'warning' | 'error' | 'info'
> = {
  pending: 'warning',
  passed: 'success',
  failed: 'error',
  overridden: 'info',
};

export default function GatesTable({ releaseId, gates, onRefresh }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  // Users for criterion assignee select — lite endpoint is tenant-member-accessible
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    api.get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([])); // assignee select stays empty on failure
  }, []);

  // Gate type vocabulary (Phase 9 C2, reusing Task 9's gateTypeSlice rather
  // than a second client). GET /gate-types is open to any tenant member and
  // returns every type regardless of is_active — needed here to resolve the
  // NAME of a gate already assigned to a type that has since been retired.
  const gateTypes = useSelector((s: RootState) => s.gateType.gateTypes);
  const activeGateTypes = selectActiveGateTypes(gateTypes);
  useEffect(() => {
    dispatch(fetchGateTypes());
  }, [dispatch]);

  const gateTypeById = useMemo(
    () => new Map(gateTypes.map((t) => [t.id, t])),
    [gateTypes]
  );
  // A gate may point at a type that's since been deactivated — keep it
  // selectable (rendered, not silently dropped) so its current value doesn't
  // vanish from the control, mirroring the owner/soft-deleted-group carve-out
  // elsewhere in this codebase.
  const assignedTypeIds = useMemo(
    () => new Set(gates.map((g) => g.gate_type_id).filter((id): id is number => id != null)),
    [gates]
  );
  const selectableGateTypes = useMemo(() => {
    const retiredButAssigned = gateTypes.filter(
      (t) => !t.is_active && assignedTypeIds.has(t.id)
    );
    return [...activeGateTypes, ...retiredButAssigned];
  }, [activeGateTypes, gateTypes, assignedTypeIds]);

  // Gate create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [gateName, setGateName] = useState('');
  const [gateDueDate, setGateDueDate] = useState<string>('');  // yyyy-mm-dd from <input type="date">

  // Gate decision dialog
  const [selectedGate, setSelectedGate] = useState<ReleaseGateResponse | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);

  // Waiver dialog (task 10b) — opened either from the "Waive" action on a
  // pending gate or by clicking an already-"overridden" gate's status chip.
  const [waiverGate, setWaiverGate] = useState<ReleaseGateResponse | null>(null);
  const [waiverOpen, setWaiverOpen] = useState(false);

  // Evidence (task 10b). Lazily fetched per gate on first expand — see the
  // effect below — and keyed by gate id in the store, not held locally, so
  // a fulfilled add/delete re-renders GateEvidenceList without a manual
  // refetch.
  const gateEvidenceByGate = useSelector((s: RootState) => s.release.gateEvidenceByGate);
  const [evidenceDialogGateId, setEvidenceDialogGateId] = useState<number | null>(null);

  // Expandable rows — set of gate ids that are open
  const [expandedGateIds, setExpandedGateIds] = useState<Set<number>>(new Set());

  // Fetch a gate's evidence the first time its row is expanded. Absence
  // from `gateEvidenceByGate` means "never fetched", not "no evidence" —
  // see the slice's own comment — so this only fires once per gate per
  // mount, not on every expand/collapse toggle.
  useEffect(() => {
    expandedGateIds.forEach((gateId) => {
      if (gateEvidenceByGate[gateId] === undefined) {
        dispatch(fetchGateEvidence(gateId));
      }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expandedGateIds]);

  // Criterion dialog state
  const [criterionDialogOpen, setCriterionDialogOpen] = useState(false);
  const [editingCriterion, setEditingCriterion] = useState<GateCriterion | null>(null);
  const [criterionGateId, setCriterionGateId] = useState<number | null>(null);

  const userList = useMemo(
    () => users.map((u) => ({ id: u.id, username: u.username })),
    [users]
  );

  const toggleExpand = (gateId: number) => {
    setExpandedGateIds((prev) => {
      const next = new Set(prev);
      if (next.has(gateId)) next.delete(gateId);
      else next.add(gateId);
      return next;
    });
  };

  const handleCreate = async () => {
    if (!gateName.trim() || !gateDueDate) return;
    try {
      // Picker gives yyyy-mm-dd — send as midnight UTC ISO string.
      const iso = new Date(`${gateDueDate}T00:00:00Z`).toISOString();
      await dispatch(
        createGate({
          releaseId,
          data: { name: gateName.trim(), due_date: iso },
        })
      ).unwrap();
      snackbar.success('Gate created');
      setCreateOpen(false);
      setGateName('');
      setGateDueDate('');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create gate');
    }
  };

  const handleDelete = async (gate: ReleaseGateResponse) => {
    const label = gate.name ? `gate "${gate.name}"` : 'this gate';
    if (!(await confirm({ message: `Delete ${label}?`, destructive: true }))) return;
    try {
      await dispatch(deleteGate({ releaseId, gateId: gate.id })).unwrap();
      onRefresh();
      snackbar.success('Gate deleted');
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : err instanceof Error ? err.message : 'Failed to delete gate';
      snackbar.error(msg);
    }
  };

  const handleGateTypeChange = async (gate: ReleaseGateResponse, gateTypeId: number | null) => {
    const result = await dispatch(
      updateGate({ releaseId, gateId: gate.id, data: { gate_type_id: gateTypeId } })
    );
    if (updateGate.fulfilled.match(result)) {
      snackbar.success('Gate type updated');
    } else {
      snackbar.error(result.payload ?? 'Failed to update gate type');
    }
  };

  const handleDeleteEvidence = async (gateId: number, evidence: GateEvidenceResponse) => {
    if (!(await confirm({ message: `Delete evidence "${evidence.label}"?`, destructive: true }))) return;
    const result = await dispatch(deleteGateEvidence({ gateId, evidenceId: evidence.id }));
    if (deleteGateEvidence.fulfilled.match(result)) {
      snackbar.success('Evidence deleted');
    } else {
      snackbar.error(result.payload ?? 'Failed to delete evidence');
    }
  };

  const openAddCriterion = (gateId: number) => {
    setEditingCriterion(null);
    setCriterionGateId(gateId);
    setCriterionDialogOpen(true);
  };

  const openEditCriterion = (criterion: GateCriterion) => {
    setEditingCriterion(criterion);
    setCriterionGateId(criterion.gate_id);
    setCriterionDialogOpen(true);
  };

  const handleCriterionSubmit = async (
    payload: GateCriterionCreatePayload | GateCriterionUpdatePayload
  ) => {
    try {
      if (editingCriterion) {
        await dispatch(
          updateCriterion({ criterionId: editingCriterion.id, payload })
        ).unwrap();
        snackbar.success('Criterion updated');
      } else if (criterionGateId !== null) {
        await dispatch(
          createCriterion({ releaseId, gateId: criterionGateId, payload: payload as GateCriterionCreatePayload })
        ).unwrap();
        snackbar.success('Criterion added');
      }
      setCriterionDialogOpen(false);
      // Refresh so server-computed overdue_criterion_count on each gate is up to date
      dispatch(fetchGates(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save criterion');
    }
  };

  const handleToggleCriterion = async (criterion: GateCriterion) => {
    try {
      if (criterion.status === 'done') {
        await dispatch(reopenCriterion(criterion.id)).unwrap();
      } else {
        await dispatch(completeCriterion(criterion.id)).unwrap();
      }
      // Refresh gates so auto-pass status propagates
      dispatch(fetchGates(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to update criterion');
    }
  };

  const handleDeleteCriterion = async (criterion: GateCriterion) => {
    const label = criterion.title ? `criterion "${criterion.title}"` : 'this criterion';
    if (!(await confirm({ message: `Delete ${label}?`, destructive: true }))) return;
    try {
      await dispatch(deleteCriterion(criterion.id)).unwrap();
      snackbar.success('Criterion deleted');
      dispatch(fetchGates(releaseId));
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete criterion');
    }
  };

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">Gates</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          Add Gate
        </Button>
      </Box>

      <Stack spacing={1}>
        {gates.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
            No gates defined
          </Typography>
        )}
        {gates.map((gate) => {
          const isExpanded = expandedGateIds.has(gate.id);
          const total = gate.criteria.length;
          const done = gate.criteria.filter((c) => c.status === 'done').length;

          return (
            <Paper key={gate.id} variant="outlined" sx={{ overflow: 'hidden' }}>
              {/* Gate header row */}
              <Box
                role="button"
                tabIndex={0}
                aria-expanded={isExpanded}
                aria-label={`${isExpanded ? 'Collapse' : 'Expand'} gate ${gate.name}`}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  px: 2,
                  py: 1,
                  gap: 1,
                  cursor: 'pointer',
                  '&:hover': { bgcolor: 'action.hover' },
                }}
                onClick={() => toggleExpand(gate.id)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    toggleExpand(gate.id);
                  }
                }}
              >
                <IconButton size="small" sx={{ mr: 0.5 }} tabIndex={-1} aria-hidden="true">
                  {isExpanded ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                </IconButton>

                <Typography variant="body2" sx={{ fontWeight: 500, flex: 1 }}>
                  {gate.name}
                </Typography>

                {/* Gate type — shown and settable inline; the first edit
                    affordance updateGate has ever had a caller for. Click
                    stops propagation so opening it doesn't toggle the row. */}
                <Box
                  sx={{ minWidth: 150 }}
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <Select<string>
                    size="small"
                    displayEmpty
                    fullWidth
                    inputProps={{ 'aria-label': `Type for gate ${gate.name}` }}
                    value={gate.gate_type_id != null ? String(gate.gate_type_id) : ''}
                    onChange={(e) => {
                      const v = e.target.value;
                      handleGateTypeChange(gate, v === '' ? null : Number(v));
                    }}
                    renderValue={(value) => {
                      if (value === '') {
                        return (
                          <Typography variant="body2" color="text.secondary">
                            Untyped
                          </Typography>
                        );
                      }
                      const t = gateTypeById.get(Number(value));
                      return (
                        <Typography variant="body2">
                          {t ? t.name : `Type #${value}`}
                        </Typography>
                      );
                    }}
                  >
                    <MenuItem value="">
                      <em>Untyped</em>
                    </MenuItem>
                    {selectableGateTypes.map((t) => (
                      <MenuItem key={t.id} value={String(t.id)}>
                        {t.name}
                        {!t.is_active ? ' (inactive)' : ''}
                      </MenuItem>
                    ))}
                  </Select>
                </Box>

                <Chip
                  size="small"
                  variant="outlined"
                  label={`Due ${gate.due_date.slice(0, 10)}`}
                />

                {gate.status === 'overridden' ? (
                  // An expired waiver must read as visibly distinct from a
                  // live one — the readiness verdict treats it as a BLOCKER
                  // again (waiver_expired), so a chip that still just says
                  // "overridden" in the same info colour would contradict
                  // the verdict right next to it.
                  <Tooltip
                    title={
                      gate.waiver?.state === 'expired'
                        ? 'Waiver expired — view the waiver'
                        : 'View the waiver'
                    }
                  >
                    <Chip
                      size="small"
                      label={gate.waiver?.state === 'expired' ? 'overridden (expired)' : gate.status}
                      color={gate.waiver?.state === 'expired' ? 'error' : STATUS_COLORS[gate.status] ?? 'default'}
                      onClick={(e) => {
                        e.stopPropagation();
                        setWaiverGate(gate);
                        setWaiverOpen(true);
                      }}
                    />
                  </Tooltip>
                ) : (
                  <Chip
                    size="small"
                    label={gate.status}
                    color={STATUS_COLORS[gate.status] ?? 'default'}
                  />
                )}

                {total > 0 && (
                  <Tooltip title={`${done} of ${total} criteria complete`}>
                    <Chip
                      size="small"
                      label={`${done}/${total} done`}
                      variant="outlined"
                      color={done === total ? 'success' : 'default'}
                    />
                  </Tooltip>
                )}

                {gate.overdue_criterion_count > 0 && (
                  <Chip
                    size="small"
                    label={`${gate.overdue_criterion_count} overdue`}
                    color="error"
                  />
                )}

                {/* Action buttons — stop propagation so they don't toggle expand */}
                <Box sx={{ display: 'flex', gap: 0.5 }} onClick={(e) => e.stopPropagation()}>
                  {gate.status === 'pending' && (
                    <Button
                      size="small"
                      startIcon={<GavelIcon fontSize="small" />}
                      onClick={() => {
                        setSelectedGate(gate);
                        setDecisionOpen(true);
                      }}
                    >
                      Decide
                    </Button>
                  )}
                  <Button
                    size="small"
                    color="error"
                    onClick={() => handleDelete(gate)}
                  >
                    <DeleteIcon fontSize="small" />
                  </Button>
                </Box>
              </Box>

              {/* Expandable criteria section */}
              <Collapse in={isExpanded} unmountOnExit>
                <Divider />
                <Box sx={{ bgcolor: 'background.default' }}>
                  {gate.criteria.length === 0 && (
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ pl: 4, py: 1 }}
                    >
                      No criteria yet.
                    </Typography>
                  )}
                  {gate.criteria.map((criterion) => (
                    <CriterionRow
                      key={criterion.id}
                      criterion={criterion}
                      onToggle={handleToggleCriterion}
                      onEdit={openEditCriterion}
                      onDelete={handleDeleteCriterion}
                    />
                  ))}
                  <Box sx={{ pl: 4, py: 1 }}>
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={(e) => {
                        e.stopPropagation();
                        openAddCriterion(gate.id);
                      }}
                    >
                      Add criterion
                    </Button>
                  </Box>

                  {/* Waiver (task 10c) — same placement rule task 10b set
                      for Evidence: inside the expand panel, not a seventh
                      always-visible header control. Only rendered for an
                      overridden gate; clicking through re-opens the same
                      WaiverDialog the status chip already opens. */}
                  {gate.status === 'overridden' && (
                    <>
                      <Divider />
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', pl: 4, pr: 2, pt: 1, pb: 1 }}>
                        <Box>
                          <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase' }}>
                            Waiver
                          </Typography>
                          {gate.waiver ? (
                            <Stack spacing={0.5} sx={{ mt: 0.5 }}>
                              <Typography variant="body2">
                                Approved by{' '}
                                {gate.waiver.approved_by_username ?? `user #${gate.waiver.approved_by_user_id}`}
                                {`: "${gate.waiver.reason}"`}
                              </Typography>
                              <Box>
                                <WaiverChip expiresAt={gate.waiver.expires_at} state={gate.waiver.state} />
                              </Box>
                              {gate.waiver.remediation && (
                                <Typography variant="body2">
                                  <strong>Remediation:</strong> {gate.waiver.remediation}
                                </Typography>
                              )}
                            </Stack>
                          ) : (
                            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                              No waiver record (overridden before waiver tracking).
                            </Typography>
                          )}
                        </Box>
                        <Button
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation();
                            setWaiverGate(gate);
                            setWaiverOpen(true);
                          }}
                        >
                          View waiver
                        </Button>
                      </Box>
                    </>
                  )}

                  {/* Evidence (task 10b) — kept inside the expand panel
                      rather than the header row, which was already dense
                      before this task. */}
                  <Divider />
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', pl: 4, pr: 2, pt: 1 }}>
                    <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase' }}>
                      Evidence
                    </Typography>
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={(e) => {
                        e.stopPropagation();
                        setEvidenceDialogGateId(gate.id);
                      }}
                    >
                      Add evidence
                    </Button>
                  </Box>
                  <GateEvidenceList
                    releaseId={releaseId}
                    evidence={gateEvidenceByGate[gate.id] ?? []}
                    onDelete={(evidence) => handleDeleteEvidence(gate.id, evidence)}
                  />
                </Box>
              </Collapse>
            </Paper>
          );
        })}
      </Stack>

      {/* Create gate dialog */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Add Gate</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Name"
              required
              fullWidth
              value={gateName}
              onChange={(e) => setGateName(e.target.value)}
            />
            <TextField
              label="Due date"
              type="date"
              required
              fullWidth
              value={gateDueDate}
              onChange={(e) => setGateDueDate(e.target.value)}
              InputLabelProps={{ shrink: true }}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={!gateName.trim() || !gateDueDate}
          >
            Add
          </Button>
        </DialogActions>
      </Dialog>

      {/* Criterion create/edit dialog */}
      <CriterionDialog
        open={criterionDialogOpen}
        initial={editingCriterion}
        users={userList}
        onClose={() => setCriterionDialogOpen(false)}
        onSubmit={handleCriterionSubmit}
      />

      {confirmDialog}
      <GateDecisionDialog
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
        releaseId={releaseId}
        gate={selectedGate}
        onWaiveInstead={() => {
          setWaiverGate(selectedGate);
          setWaiverOpen(true);
        }}
      />

      <WaiverDialog
        open={waiverOpen}
        onClose={() => setWaiverOpen(false)}
        releaseId={releaseId}
        gate={waiverGate}
        users={userList}
      />

      {evidenceDialogGateId !== null && (() => {
        const evidenceGate = gates.find((g) => g.id === evidenceDialogGateId);
        const evidenceGateType = evidenceGate?.gate_type_id != null
          ? gateTypeById.get(evidenceGate.gate_type_id)
          : undefined;
        return (
          <AddEvidenceDialog
            open
            onClose={() => setEvidenceDialogGateId(null)}
            releaseId={releaseId}
            gateId={evidenceDialogGateId}
            expectedEvidence={evidenceGateType?.expected_evidence ?? []}
            requiresDeploymentLink={evidenceGateType?.requires_deployment_link ?? false}
          />
        );
      })()}
    </Box>
  );
}
