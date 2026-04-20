/**
 * PhasesTable — MUI DataGrid for editing test phases inline.
 * Date editing here drives the Gantt above.
 */
import { useMemo, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Box,
  Button,
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
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { AppDispatch } from '../../store';
import {
  createPhase,
  updatePhase,
  deletePhase,
} from '../../store/releaseSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import { toIsoDatetime } from '../../utils/dates';
import type { TestPhaseResponse } from '../../types/release';

interface Props {
  releaseId: number;
  phases: TestPhaseResponse[];
}

const PHASE_STATUSES = ['planned', 'in_progress', 'completed', 'blocked'];

export default function PhasesTable({ releaseId, phases }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<TestPhaseResponse | null>(null);
  const [name, setName] = useState('');
  const [phaseStatus, setPhaseStatus] = useState('planned');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const openCreate = () => {
    setEditing(null);
    setName('');
    setPhaseStatus('planned');
    setStartDate('');
    setEndDate('');
    setDialogOpen(true);
  };

  const openEdit = (phase: TestPhaseResponse) => {
    setEditing(phase);
    setName(phase.name);
    setPhaseStatus(phase.status);
    setStartDate(phase.start_date ? phase.start_date.slice(0, 10) : '');
    setEndDate(phase.end_date ? phase.end_date.slice(0, 10) : '');
    setDialogOpen(true);
  };

  const handleClose = () => {
    setDialogOpen(false);
    setEditing(null);
  };

  const handleSave = async () => {
    if (!name.trim()) return;
    try {
      if (editing) {
        await dispatch(
          updatePhase({
            releaseId,
            phaseId: editing.id,
            data: {
              name: name.trim(),
              status: phaseStatus,
              start_date: toIsoDatetime(startDate),
              end_date: toIsoDatetime(endDate),
            },
          })
        ).unwrap();
        snackbar.success('Phase updated');
      } else {
        await dispatch(
          createPhase({
            releaseId,
            data: {
              name: name.trim(),
              order: phases.length + 1,
              status: phaseStatus,
              start_date: toIsoDatetime(startDate),
              end_date: toIsoDatetime(endDate),
            },
          })
        ).unwrap();
        snackbar.success('Phase created');
      }
      handleClose();
    } catch (err) {
      const axiosErr = err as { response?: { data?: { detail?: unknown } } };
      const detail = axiosErr?.response?.data?.detail;
      const msg = typeof detail === 'string'
        ? detail
        : Array.isArray(detail) && detail[0]?.msg
          ? `${(detail[0] as { loc?: unknown[] }).loc?.join?.('.') ?? 'field'}: ${
              (detail[0] as { msg: string }).msg
            }`
          : err instanceof Error ? err.message : 'Failed to save phase';
      snackbar.error(msg);
    }
  };

  const handleDelete = async (phaseId: number) => {
    if (!(await confirm({ message: 'Delete this phase?', destructive: true }))) return;
    try {
      await dispatch(deletePhase({ releaseId, phaseId })).unwrap();
      snackbar.success('Phase deleted');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete phase');
    }
  };

  const columns = useMemo<GridColDef<TestPhaseResponse>[]>(
    () => [
      { field: 'order', headerName: '#', width: 60 },
      { field: 'name', headerName: 'Name', flex: 1, minWidth: 150 },
      { field: 'status', headerName: 'Status', width: 120 },
      {
        field: 'start_date',
        headerName: 'Start',
        width: 120,
        valueFormatter: (p) =>
          p.value ? new Date(p.value as string).toLocaleDateString() : '—',
      },
      {
        field: 'end_date',
        headerName: 'End',
        width: 120,
        valueFormatter: (p) =>
          p.value ? new Date(p.value as string).toLocaleDateString() : '—',
      },
      {
        field: '_actions',
        headerName: '',
        width: 80,
        sortable: false,
        renderCell: (params) => (
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
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [releaseId]
  );

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">Test Phases</Typography>
        <Button size="small" startIcon={<AddIcon />} onClick={openCreate}>
          Add Phase
        </Button>
      </Box>

      <Box sx={{ height: 300 }}>
        <DataTable<TestPhaseResponse>
          storageKey="release-phases-table"
          rows={phases}
          columns={columns}
          loading={false}
          emptyMessage="No phases yet"
          onRowClick={(params: GridRowParams<TestPhaseResponse>) => openEdit(params.row)}
        />
      </Box>

      {confirmDialog}
      <Dialog open={dialogOpen} onClose={handleClose} maxWidth="xs" fullWidth>
        <DialogTitle>{editing ? 'Edit Phase' : 'Add Phase'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Name"
              required
              fullWidth
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <TextField
              select
              label="Status"
              fullWidth
              value={phaseStatus}
              onChange={(e) => setPhaseStatus(e.target.value)}
            >
              {PHASE_STATUSES.map((s) => (
                <MenuItem key={s} value={s}>
                  {s}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Start Date"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            <TextField
              label="End Date"
              type="date"
              fullWidth
              InputLabelProps={{ shrink: true }}
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={!name.trim()}>
            {editing ? 'Save' : 'Add'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
