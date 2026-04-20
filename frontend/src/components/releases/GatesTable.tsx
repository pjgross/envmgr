/**
 * GatesTable — expandable list of release gates with per-gate criteria.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
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
  deleteGate,
  fetchGates,
  createCriterion,
  updateCriterion,
  completeCriterion,
  reopenCriterion,
  deleteCriterion,
} from '../../store/releaseSlice';
import api from '../../services/api';
import { useSnackbar } from '../../hooks/useSnackbar';
import GateDecisionDialog from './GateDecisionDialog';
import CriterionRow from './CriterionRow';
import CriterionDialog from './CriterionDialog';
import type { ReleaseGateResponse, TestPhaseResponse } from '../../types/release';
import type { GateCriterion, GateCriterionCreatePayload, GateCriterionUpdatePayload } from '../../types/gateCriterion';

interface Props {
  releaseId: number;
  gates: ReleaseGateResponse[];
  phases: TestPhaseResponse[];
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

export default function GatesTable({ releaseId, gates, phases, onRefresh }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();

  // Users for criterion assignee select — lite endpoint is tenant-member-accessible
  const [users, setUsers] = useState<Array<{ id: number; username: string }>>([]);
  useEffect(() => {
    api.get<Array<{ id: number; username: string }>>('/tenant/users/lite')
      .then((r) => setUsers(r.data))
      .catch(() => setUsers([])); // assignee select stays empty on failure
  }, []);

  // Gate create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [gateName, setGateName] = useState('');
  const [gatePhaseId, setGatePhaseId] = useState<number | ''>('');

  // Gate decision dialog
  const [selectedGate, setSelectedGate] = useState<ReleaseGateResponse | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);

  // Expandable rows — set of gate ids that are open
  const [expandedGateIds, setExpandedGateIds] = useState<Set<number>>(new Set());

  // Criterion dialog state
  const [criterionDialogOpen, setCriterionDialogOpen] = useState(false);
  const [editingCriterion, setEditingCriterion] = useState<GateCriterion | null>(null);
  const [criterionGateId, setCriterionGateId] = useState<number | null>(null);

  const phaseNameMap = useMemo(
    () => new Map(phases.map((p) => [p.id, p.name])),
    [phases]
  );

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
    if (!gateName.trim()) return;
    try {
      await dispatch(
        createGate({
          releaseId,
          data: {
            name: gateName.trim(),
            test_phase_id: gatePhaseId !== '' ? gatePhaseId : undefined,
          },
        })
      ).unwrap();
      snackbar.success('Gate created');
      setCreateOpen(false);
      setGateName('');
      setGatePhaseId('');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create gate');
    }
  };

  const handleDelete = async (gateId: number) => {
    if (!confirm('Delete this gate?')) return;
    try {
      await dispatch(deleteGate({ releaseId, gateId })).unwrap();
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
    if (!confirm('Delete this criterion?')) return;
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

                {gate.test_phase_id && (
                  <Chip
                    size="small"
                    label={phaseNameMap.get(gate.test_phase_id) ?? `Phase ${gate.test_phase_id}`}
                    variant="outlined"
                  />
                )}

                <Chip
                  size="small"
                  label={gate.status}
                  color={STATUS_COLORS[gate.status] ?? 'default'}
                />

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
                    onClick={() => handleDelete(gate.id)}
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
              select
              label="Phase (optional)"
              fullWidth
              value={gatePhaseId}
              onChange={(e) =>
                setGatePhaseId(e.target.value === '' ? '' : Number(e.target.value))
              }
            >
              <MenuItem value="">None</MenuItem>
              {phases.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.name}
                </MenuItem>
              ))}
            </TextField>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={!gateName.trim()}
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

      <GateDecisionDialog
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
        releaseId={releaseId}
        gate={selectedGate}
      />
    </Box>
  );
}
