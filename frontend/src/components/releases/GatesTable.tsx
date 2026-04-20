/**
 * GatesTable — MUI DataGrid listing release gates with action buttons.
 */
import { useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import GavelIcon from '@mui/icons-material/Gavel';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { AppDispatch } from '../../store';
import { createGate, deleteGate } from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import GateDecisionDialog from './GateDecisionDialog';
import type { ReleaseGateResponse, TestPhaseResponse } from '../../types/release';

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

  const [createOpen, setCreateOpen] = useState(false);
  const [gateName, setGateName] = useState('');
  const [gateCriteria, setGateCriteria] = useState('');
  const [gatePhaseId, setGatePhaseId] = useState<number | ''>('');
  const [selectedGate, setSelectedGate] = useState<ReleaseGateResponse | null>(null);
  const [decisionOpen, setDecisionOpen] = useState(false);

  const handleCreate = async () => {
    if (!gateName.trim()) return;
    try {
      await dispatch(
        createGate({
          releaseId,
          data: {
            name: gateName.trim(),
            acceptance_criteria: gateCriteria.trim() || undefined,
            test_phase_id: gatePhaseId !== '' ? gatePhaseId : undefined,
          },
        })
      ).unwrap();
      snackbar.success('Gate created');
      setCreateOpen(false);
      setGateName('');
      setGateCriteria('');
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

  const phaseNameMap = useMemo(
    () => new Map(phases.map((p) => [p.id, p.name])),
    [phases]
  );

  const columns = useMemo<GridColDef<ReleaseGateResponse>[]>(
    () => [
      { field: 'name', headerName: 'Gate', flex: 1, minWidth: 150 },
      {
        field: 'test_phase_id',
        headerName: 'Phase',
        width: 150,
        valueFormatter: (p) =>
          p.value ? (phaseNameMap.get(p.value as number) ?? `Phase ${p.value}`) : '—',
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 120,
        renderCell: (params) => (
          <Chip
            label={params.row.status}
            color={STATUS_COLORS[params.row.status] ?? 'default'}
            size="small"
          />
        ),
      },
      {
        field: 'acceptance_criteria',
        headerName: 'Criteria',
        flex: 1,
        minWidth: 200,
        renderCell: (params) => (
          <Typography variant="body2" noWrap color="text.secondary">
            {params.row.acceptance_criteria ?? '—'}
          </Typography>
        ),
      },
      {
        field: '_actions',
        headerName: '',
        width: 120,
        sortable: false,
        renderCell: (params) => (
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {params.row.status === 'pending' && (
              <Button
                size="small"
                startIcon={<GavelIcon fontSize="small" />}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedGate(params.row);
                  setDecisionOpen(true);
                }}
              >
                Decide
              </Button>
            )}
            <Button
              size="small"
              color="error"
              onClick={(e) => {
                e.stopPropagation();
                handleDelete(params.row.id);
              }}
            >
              <DeleteIcon fontSize="small" />
            </Button>
          </Box>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [releaseId, phaseNameMap]
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">Gates</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          Add Gate
        </Button>
      </Box>

      <Box sx={{ height: 280 }}>
        <DataTable<ReleaseGateResponse>
          storageKey="release-gates-table"
          rows={gates}
          columns={columns}
          loading={false}
          emptyMessage="No gates defined"
        />
      </Box>

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
            <TextField
              label="Acceptance Criteria"
              multiline
              rows={2}
              fullWidth
              value={gateCriteria}
              onChange={(e) => setGateCriteria(e.target.value)}
            />
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

      <GateDecisionDialog
        open={decisionOpen}
        onClose={() => setDecisionOpen(false)}
        releaseId={releaseId}
        gate={selectedGate}
      />
    </Box>
  );
}
