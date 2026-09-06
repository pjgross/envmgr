/**
 * GoNoGoPerspectivesPanel — the tenant-configurable vocabulary a Go/No-Go
 * decision's sign-offs are recorded against (Phase 9 C3), seeded with
 * Quality / Process / Acceptance.
 *
 * Reads are open to any tenant member; only writes are Admin — the same
 * split `app/api/v1/go_no_go.py`'s `perspectives_router` makes, deliberately
 * unlike /tenant/users (the false analogy a B3a reviewer caught: show,
 * don't hide, for a non-admin). There is no delete — a perspective is
 * retired via the Active toggle, never removed, so sign-offs already
 * recorded against it keep resolving its name, via
 * `go_no_go_service.perspective_names_for` (see that function's docstring:
 * it resolves the perspective's CURRENT name, so a rename here changes what
 * every past decision's sign-off table displays too — a deliberate choice,
 * not a staleness bug).
 */
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
  fetchPerspectives,
  createPerspective,
  updatePerspective,
} from '../../store/goNoGoSlice';
import type { GoNoGoPerspectiveRead } from '../../types/goNoGo';

export default function GoNoGoPerspectivesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { perspectives, loading } = useSelector((s: RootState) => s.goNoGo);

  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newOrder, setNewOrder] = useState(100);
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<GoNoGoPerspectiveRead | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editOrder, setEditOrder] = useState(0);
  const [editActive, setEditActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchPerspectives(true));
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createPerspective({
        name: newName.trim(),
        description: newDescription.trim() ? newDescription.trim() : null,
        sort_order: newOrder,
        is_active: true,
      })
    );
    if (createPerspective.rejected.match(result)) {
      // `result.payload`, never `result.error.message` — a duplicate name
      // is a 409 whose body IS the message ("A perspective named X already
      // exists"); the default serializer would flatten it to a status code.
      setCreateError(result.payload ?? 'Failed to create perspective');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewDescription('');
    setNewOrder(100);
  };

  const openEdit = (row: GoNoGoPerspectiveRead) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditDescription(row.description ?? '');
    setEditOrder(row.sort_order);
    setEditActive(row.is_active);
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updatePerspective({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          description: editDescription.trim() ? editDescription.trim() : null,
          sort_order: editOrder,
          is_active: editActive,
        },
      })
    );
    if (updatePerspective.rejected.match(result)) {
      setEditError(result.payload ?? 'Failed to update perspective');
      return;
    }
    setEditTarget(null);
  };

  const columns: GridColDef<GoNoGoPerspectiveRead>[] = [
    {
      field: 'name',
      headerName: 'Perspective',
      flex: 1,
      renderCell: (params) => <Chip label={params.row.name} size="small" />,
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 1.5,
      renderCell: (params) => params.row.description ?? '—',
    },
    { field: 'sort_order', headerName: 'Order', width: 90 },
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
    ...(canWrite
      ? ([
          {
            field: 'actions',
            headerName: '',
            width: 100,
            sortable: false,
            renderCell: (params) => (
              <Button size="small" onClick={() => openEdit(params.row)}>
                Edit
              </Button>
            ),
          },
        ] satisfies GridColDef<GoNoGoPerspectiveRead>[])
      : []),
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Go/No-Go Perspectives</Typography>
        {canWrite && (
          <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
            + New Perspective
          </Button>
        )}
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        The vocabulary a Go/No-Go decision's sign-offs are recorded against.
        There is no delete — an inactive perspective is hidden from pickers
        for a new decision but keeps naming the sign-offs already recorded
        against it.
      </Typography>

      {!canWrite && (
        <Alert severity="info" sx={{ mb: 2 }}>
          You can view these perspectives. Adding or changing one requires an
          Admin.
        </Alert>
      )}

      <DataTable
        storageKey="admin-go-no-go-perspectives"
        emptyMessage="No perspectives configured yet."
        rows={perspectives}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Perspective</DialogTitle>
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
        <DialogTitle>Edit Perspective</DialogTitle>
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
    </Box>
  );
}
