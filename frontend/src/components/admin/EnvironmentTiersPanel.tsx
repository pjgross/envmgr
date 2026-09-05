import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
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
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchEnvironmentTiers,
  createEnvironmentTier,
  updateEnvironmentTier,
  deleteEnvironmentTier,
} from '../../store/environmentTierSlice';
import type { EnvironmentTierResponse } from '../../types/environmentTier';

export default function EnvironmentTiersPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { tiers, loading } = useSelector((s: RootState) => s.environmentTier);

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState('#90A4AE');
  const [newOrder, setNewOrder] = useState(100);
  // '' means "use the tenant default" — BLANK, never pre-filled with the
  // tenant's idle_threshold_days. Pre-filling it with, say, 30 would turn
  // every save into an explicit per-tier override nobody asked for, silently
  // detaching this tier from future tenant-default changes. Kept as a
  // string (not `number | null`) so the field can hold an in-progress empty
  // input without coercing to 0 — Number('') is 0, not a usable sentinel.
  const [newIdleThreshold, setNewIdleThreshold] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<EnvironmentTierResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('');
  const [editOrder, setEditOrder] = useState(0);
  const [editActive, setEditActive] = useState(true);
  const [editIdleThreshold, setEditIdleThreshold] = useState('');
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteTarget, setDeleteTarget] = useState<EnvironmentTierResponse | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchEnvironmentTiers());
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createEnvironmentTier({
        name: newName.trim(),
        color: newColor,
        display_order: newOrder,
        is_active: true,
        // '' -> null: no override at creation unless the admin typed one.
        idle_threshold_days: newIdleThreshold.trim() ? Number(newIdleThreshold) : null,
      })
    );
    if (createEnvironmentTier.rejected.match(result)) {
      setCreateError(result.payload ?? result.error.message ?? 'Failed to create tier');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewIdleThreshold('');
  };

  const openEdit = (row: EnvironmentTierResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditColor(row.color ?? '#90A4AE');
    setEditOrder(row.display_order);
    setEditActive(row.is_active);
    // BLANK when null — not the tenant default. See the state comment above.
    setEditIdleThreshold(
      row.idle_threshold_days === null ? '' : String(row.idle_threshold_days)
    );
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateEnvironmentTier({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          color: editColor,
          display_order: editOrder,
          is_active: editActive,
          // Always sent, blank or not — the backend reads this via
          // model_fields_set, so OMITTING the key (rather than sending
          // explicit null) is how you'd accidentally leave a stale override
          // in place. A blank field must send null to actually clear it.
          idle_threshold_days: editIdleThreshold.trim()
            ? Number(editIdleThreshold)
            : null,
        },
      })
    );
    if (updateEnvironmentTier.rejected.match(result)) {
      setEditError(result.payload ?? result.error.message ?? 'Failed to update tier');
      return;
    }
    setEditTarget(null);
  };

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return;
    setDeleteError(null);
    const result = await dispatch(deleteEnvironmentTier(deleteTarget.id));
    if (deleteEnvironmentTier.rejected.match(result)) {
      // The backend refuses 409 while environments still reference the tier.
      setDeleteError(result.payload ?? result.error.message ?? 'Failed to delete tier');
      return;
    }
    setDeleteTarget(null);
  };

  const columns: GridColDef<EnvironmentTierResponse>[] = [
    {
      field: 'name',
      headerName: 'Tier',
      flex: 1,
      renderCell: (params) => (
        <Chip
          label={params.row.name}
          size="small"
          sx={{
            bgcolor: params.row.color ?? undefined,
            color: params.row.color ? 'common.white' : undefined,
          }}
        />
      ),
    },
    { field: 'display_order', headerName: 'Order', width: 100 },
    {
      field: 'category',
      headerName: 'Standard tier',
      flex: 1,
      renderCell: (params) => params.row.category ?? '—',
    },
    {
      field: 'idle_threshold_days',
      headerName: 'Idle override',
      width: 150,
      renderCell: (params) =>
        params.row.idle_threshold_days === null
          ? 'Uses tenant default'
          : `${params.row.idle_threshold_days} days`,
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 120,
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
        <Typography variant="h6">Environment Tiers</Typography>
        <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
          + New Tier
        </Button>
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        An inactive tier is hidden from pickers but still shown on environments
        already using it. A tier in use cannot be deleted.
      </Typography>

      <DataTable
        storageKey="admin-environment-tiers"
        emptyMessage="No environment tiers configured yet."
        rows={tiers}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Environment Tier</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createError && <Alert severity="error">{createError}</Alert>}
          <TextField
            label="Name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <TextField
            label="Colour"
            type="color"
            value={newColor}
            onChange={(e) => setNewColor(e.target.value)}
          />
          <TextField
            label="Display order"
            type="number"
            value={newOrder}
            onChange={(e) => setNewOrder(Number(e.target.value))}
            helperText="Lower numbers sort first — tiers have a progression, not an alphabet."
          />
          <TextField
            label="Idle threshold override (days)"
            type="number"
            value={newIdleThreshold}
            onChange={(e) => setNewIdleThreshold(e.target.value)}
            inputProps={{ min: 1, max: 3650 }}
            helperText="Leave blank to use the tenant's default idle threshold (Lifecycle & Decommissioning tab). A Dev sandbox and a DR environment don't go idle at the same rate."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onClose={() => setEditTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Environment Tier</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {editError && <Alert severity="error">{editError}</Alert>}
          <TextField
            label="Name"
            required
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <TextField
            label="Colour"
            type="color"
            value={editColor}
            onChange={(e) => setEditColor(e.target.value)}
          />
          <TextField
            label="Display order"
            type="number"
            value={editOrder}
            onChange={(e) => setEditOrder(Number(e.target.value))}
            helperText="Lower numbers sort first — tiers have a progression, not an alphabet."
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
          <TextField
            label="Idle threshold override (days)"
            type="number"
            value={editIdleThreshold}
            onChange={(e) => setEditIdleThreshold(e.target.value)}
            inputProps={{ min: 1, max: 3650 }}
            helperText="Leave blank to use the tenant's default idle threshold. Clearing this field and saving removes the override — it does not set it to blank forever."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave} disabled={!editName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Environment Tier</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Delete <strong>{deleteTarget?.name}</strong>? Environments still using
            it will block this.
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
