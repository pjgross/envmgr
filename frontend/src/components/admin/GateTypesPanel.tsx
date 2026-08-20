import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchGateTypes,
  createGateType,
  updateGateType,
  deleteGateType,
} from '../../store/gateTypeSlice';
import type { GateFailureBehaviour, GateTypeResponse } from '../../types/gateType';

// C2 ADVISES, IT NEVER BLOCKS. Nothing here may say plain "Blocks" — a typed
// gate's failure_behaviour only changes how the gate reads in the readiness
// verdict; it never refuses a deployment or a release transition. See
// docs/superpowers/specs (Task 8's guard) for the backend half of this promise.
const FAILURE_BEHAVIOUR_LABELS: Record<GateFailureBehaviour, string> = {
  block: 'Blocks (advisory)',
  warn: 'Warns',
  accept_with_exception: 'Accept with exception',
};

const FAILURE_BEHAVIOUR_OPTIONS: GateFailureBehaviour[] = [
  'block',
  'warn',
  'accept_with_exception',
];

interface EvidenceEditorProps {
  value: string[];
  onChange: (next: string[]) => void;
}

function EvidenceEditor({ value, onChange }: EvidenceEditorProps) {
  const [draft, setDraft] = useState('');

  const addEntry = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (value.some((v) => v.toLowerCase() === trimmed.toLowerCase())) {
      setDraft('');
      return;
    }
    onChange([...value, trimmed]);
    setDraft('');
  };

  return (
    <Box>
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField
          label="Add expected evidence"
          size="small"
          fullWidth
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addEntry();
            }
          }}
        />
        <Button size="small" onClick={addEntry} disabled={!draft.trim()}>
          Add
        </Button>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ mt: 1, flexWrap: 'wrap', gap: 1 }}>
        {value.map((item) => (
          <Chip
            key={item}
            label={item}
            size="small"
            onDelete={() => onChange(value.filter((v) => v !== item))}
          />
        ))}
        {value.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No evidence kinds recorded yet.
          </Typography>
        )}
      </Stack>
    </Box>
  );
}

export default function GateTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { gateTypes, loading } = useSelector((s: RootState) => s.gateType);

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newFailureBehaviour, setNewFailureBehaviour] =
    useState<GateFailureBehaviour>('warn');
  const [newEvidence, setNewEvidence] = useState<string[]>([]);
  const [newRequiresDeploymentLink, setNewRequiresDeploymentLink] = useState(false);
  const [newOrder, setNewOrder] = useState(100);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<GateTypeResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editFailureBehaviour, setEditFailureBehaviour] =
    useState<GateFailureBehaviour>('warn');
  const [editEvidence, setEditEvidence] = useState<string[]>([]);
  const [editRequiresDeploymentLink, setEditRequiresDeploymentLink] = useState(false);
  const [editOrder, setEditOrder] = useState(0);
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<GateTypeResponse | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchGateTypes());
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createGateType({
        name: newName.trim(),
        description: newDescription.trim() ? newDescription.trim() : null,
        failure_behaviour: newFailureBehaviour,
        expected_evidence: newEvidence,
        requires_deployment_link: newRequiresDeploymentLink,
        display_order: newOrder,
        is_active: true,
      })
    );
    if (createGateType.rejected.match(result)) {
      setCreateError(result.payload ?? result.error.message ?? 'Failed to create gate type');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewDescription('');
    setNewFailureBehaviour('warn');
    setNewEvidence([]);
    setNewRequiresDeploymentLink(false);
    setNewOrder(100);
  };

  const openEdit = (row: GateTypeResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditDescription(row.description ?? '');
    setEditFailureBehaviour(row.failure_behaviour);
    setEditEvidence(row.expected_evidence);
    setEditRequiresDeploymentLink(row.requires_deployment_link);
    setEditOrder(row.display_order);
    setEditActive(row.is_active);
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateGateType({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          description: editDescription.trim() ? editDescription.trim() : null,
          failure_behaviour: editFailureBehaviour,
          expected_evidence: editEvidence,
          requires_deployment_link: editRequiresDeploymentLink,
          display_order: editOrder,
          is_active: editActive,
        },
      })
    );
    if (updateGateType.rejected.match(result)) {
      setEditError(result.payload ?? result.error.message ?? 'Failed to update gate type');
      return;
    }
    setEditTarget(null);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    const result = await dispatch(deleteGateType(deleteTarget.id));
    if (deleteGateType.rejected.match(result)) {
      setDeleteError(result.payload ?? result.error.message ?? 'Failed to delete gate type');
      return;
    }
    setDeleteTarget(null);
  };

  const columns: GridColDef<GateTypeResponse>[] = [
    {
      field: 'name',
      headerName: 'Gate type',
      flex: 1,
      renderCell: (params) => <Chip label={params.row.name} size="small" />,
    },
    { field: 'display_order', headerName: 'Order', width: 90 },
    {
      field: 'category',
      headerName: 'Standard category',
      flex: 1,
      renderCell: (params) => params.row.category ?? '—',
    },
    {
      field: 'failure_behaviour',
      headerName: 'Verdict behaviour',
      width: 190,
      renderCell: (params) => FAILURE_BEHAVIOUR_LABELS[params.row.failure_behaviour],
    },
    {
      field: 'expected_evidence',
      headerName: 'Expected evidence',
      flex: 1.5,
      renderCell: (params) =>
        params.row.expected_evidence.length ? (
          <Stack direction="row" spacing={0.5} sx={{ flexWrap: 'wrap', gap: 0.5, py: 0.5 }}>
            {params.row.expected_evidence.map((item) => (
              <Chip key={item} label={item} size="small" variant="outlined" />
            ))}
          </Stack>
        ) : (
          '—'
        ),
    },
    {
      field: 'requires_deployment_link',
      headerName: 'Needs deployment',
      width: 150,
      renderCell: (params) => (params.row.requires_deployment_link ? 'Yes' : 'No'),
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 110,
      renderCell: (params) => (
        <Chip
          label={params.row.is_active ? 'Active' : 'Inactive'}
          color={params.row.is_active ? 'success' : 'default'}
          size="small"
        />
      ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 160,
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button size="small" onClick={() => openEdit(params.row)}>
            Edit
          </Button>
          <Button size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
            Delete
          </Button>
        </Box>
      ),
    },
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Gate Types</Typography>
        <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
          + New Gate Type
        </Button>
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        The vocabulary release gates are typed against. An inactive gate type
        is hidden from pickers but still shown on gates already using it.
      </Typography>

      <DataGrid
        rows={gateTypes}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Gate Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createError && <Alert severity="error">{createError}</Alert>}
          <TextField
            label="Name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <TextField
            label="Description"
            multiline
            minRows={2}
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
          />
          <TextField
            select
            label="Verdict behaviour"
            value={newFailureBehaviour}
            onChange={(e) =>
              setNewFailureBehaviour(e.target.value as GateFailureBehaviour)
            }
          >
            {FAILURE_BEHAVIOUR_OPTIONS.map((opt) => (
              <MenuItem key={opt} value={opt}>
                {FAILURE_BEHAVIOUR_LABELS[opt]}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="caption" color="text.secondary">
            No gate refuses a deployment or a release transition. This only
            controls how a gate of this type reads in the readiness verdict —
            as a blocker, a warning, or something that can be accepted with a
            recorded exception.
          </Typography>
          <EvidenceEditor value={newEvidence} onChange={setNewEvidence} />
          <FormControlLabel
            control={
              <Checkbox
                checked={newRequiresDeploymentLink}
                onChange={(e) => setNewRequiresDeploymentLink(e.target.checked)}
              />
            }
            label="Requires a deployment link"
          />
          <TextField
            label="Display order"
            type="number"
            value={newOrder}
            onChange={(e) => setNewOrder(Number(e.target.value))}
            helperText="Lower numbers sort first."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onClose={() => setEditTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Gate Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {editError && <Alert severity="error">{editError}</Alert>}
          <TextField
            label="Name"
            required
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <TextField
            label="Description"
            multiline
            minRows={2}
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
          />
          <TextField
            select
            label="Verdict behaviour"
            value={editFailureBehaviour}
            onChange={(e) =>
              setEditFailureBehaviour(e.target.value as GateFailureBehaviour)
            }
          >
            {FAILURE_BEHAVIOUR_OPTIONS.map((opt) => (
              <MenuItem key={opt} value={opt}>
                {FAILURE_BEHAVIOUR_LABELS[opt]}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="caption" color="text.secondary">
            No gate refuses a deployment or a release transition. This only
            controls how a gate of this type reads in the readiness verdict —
            as a blocker, a warning, or something that can be accepted with a
            recorded exception.
          </Typography>
          <EvidenceEditor value={editEvidence} onChange={setEditEvidence} />
          <FormControlLabel
            control={
              <Checkbox
                checked={editRequiresDeploymentLink}
                onChange={(e) => setEditRequiresDeploymentLink(e.target.checked)}
              />
            }
            label="Requires a deployment link"
          />
          <TextField
            label="Display order"
            type="number"
            value={editOrder}
            onChange={(e) => setEditOrder(Number(e.target.value))}
            helperText="Lower numbers sort first."
          />
          <TextField
            select
            label="Status"
            value={editActive ? 'active' : 'inactive'}
            onChange={(e) => setEditActive(e.target.value === 'active')}
          >
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="inactive">Inactive</MenuItem>
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave} disabled={!editName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Gate Type</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Delete <strong>{deleteTarget?.name}</strong>? Gates already using
            this type keep pointing at it and still render its name.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
