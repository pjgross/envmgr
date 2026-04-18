import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Typography,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Alert,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  createBookingType,
  updateBookingType,
  deleteBookingType,
} from '../../store/bookingLifecycleSlice';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';

export default function BookingTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { templates, bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTemplateId, setNewTemplateId] = useState<number | ''>('');
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit dialog
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editTemplateId, setEditTemplateId] = useState<number | ''>('');
  const [editIsActive, setEditIsActive] = useState(true);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete confirm dialog
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName || !newTemplateId) return;
    setCreateError(null);
    const result = await dispatch(
      createBookingType({
        name: newName,
        lifecycle_template_id: Number(newTemplateId),
        is_active: true,
        description: null,
        color: null,
      })
    );
    if (createBookingType.rejected.match(result)) {
      setCreateError(result.error.message ?? 'Failed to create booking type');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewTemplateId('');
  };

  const handleEditOpen = (row: BookingTypeRecord) => {
    setEditId(row.id);
    setEditName(row.name);
    setEditTemplateId(row.lifecycle_template_id);
    setEditIsActive(row.is_active);
    setEditError(null);
    setEditOpen(true);
  };

  const handleEditSave = async () => {
    if (!editName || !editTemplateId || editId === null) return;
    setEditError(null);
    const result = await dispatch(
      updateBookingType({
        id: editId,
        data: {
          name: editName,
          lifecycle_template_id: Number(editTemplateId),
          is_active: editIsActive,
        },
      })
    );
    if (updateBookingType.rejected.match(result)) {
      setEditError(result.error.message ?? 'Failed to update booking type');
      return;
    }
    setEditOpen(false);
  };

  const handleDeleteOpen = (id: number) => {
    setDeleteId(id);
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteBookingType(deleteId));
    if (deleteBookingType.rejected.match(result)) {
      setDeleteError(result.error.message ?? 'Failed to delete booking type');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
  };

  const columns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'lifecycle_template_id',
      headerName: 'Lifecycle Template',
      flex: 1,
      renderCell: (params) => {
        const tmpl = templates.find((t) => t.id === params.value);
        return tmpl?.name ?? String(params.value);
      },
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 110,
      renderCell: (params) => (
        <Chip
          label={params.value ? 'Active' : 'Inactive'}
          color={params.value ? 'success' : 'default'}
          size="small"
        />
      ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 140,
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button size="small" onClick={() => handleEditOpen(params.row as BookingTypeRecord)}>
            Edit
          </Button>
          <Button
            size="small"
            color="error"
            onClick={() => handleDeleteOpen(params.row.id as number)}
          >
            Delete
          </Button>
        </Box>
      ),
    },
  ];

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Booking Types</Typography>
        <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
          + New Type
        </Button>
      </Box>

      <DataGrid
        rows={bookingTypes}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      {/* Create dialog */}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Booking Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createError && <Alert severity="error">{createError}</Alert>}
          <TextField
            label="Name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <TextField
            select
            label="Lifecycle Template"
            required
            value={newTemplateId}
            onChange={(e) => setNewTemplateId(Number(e.target.value))}
          >
            {templates.map((t) => (
              <MenuItem key={t.id} value={t.id}>
                {t.name}
              </MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName || !newTemplateId}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      {/* Edit dialog */}
      <Dialog open={editOpen} onClose={() => setEditOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Booking Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {editError && <Alert severity="error">{editError}</Alert>}
          <TextField
            label="Name"
            required
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <TextField
            select
            label="Lifecycle Template"
            required
            value={editTemplateId}
            onChange={(e) => setEditTemplateId(Number(e.target.value))}
          >
            {templates.map((t) => (
              <MenuItem key={t.id} value={t.id}>
                {t.name}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Status"
            value={editIsActive ? 'active' : 'inactive'}
            onChange={(e) => setEditIsActive(e.target.value === 'active')}
          >
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="inactive">Inactive</MenuItem>
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleEditSave}
            disabled={!editName || !editTemplateId}
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Booking Type</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this booking type? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
