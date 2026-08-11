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
  selectBookingTemplates,
} from '../../store/bookingLifecycleSlice';
import type { BookingTypeRecord } from '../../types/bookingLifecycle';
import {
  PROTECTION_LABELS,
  PROTECTION_LEVELS,
  type ProtectionLevel,
} from '../../constants/protection';

/**
 * A blank duration field is "no preset", never zero minutes — `Number('')` is
 * 0, and the API 422s on `gt=0`. Anything unparseable collapses to null for
 * the same reason: sending NaN would serialise as `null` anyway on create, and
 * as a validation error on update.
 */
function durationToPayload(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

export default function BookingTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);
  const templates = useSelector(selectBookingTemplates);

  // Create dialog
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTemplateId, setNewTemplateId] = useState<number | ''>('');
  const [newProtection, setNewProtection] = useState<ProtectionLevel>('soft');
  const [newDuration, setNewDuration] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  // Edit dialog
  const [editOpen, setEditOpen] = useState(false);
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editTemplateId, setEditTemplateId] = useState<number | ''>('');
  const [editIsActive, setEditIsActive] = useState(true);
  const [editProtection, setEditProtection] = useState<ProtectionLevel>('soft');
  const [editDuration, setEditDuration] = useState('');
  const [editError, setEditError] = useState<string | null>(null);

  // Delete confirm dialog
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates('booking'));
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
        default_protection_level: newProtection,
        default_duration_minutes: durationToPayload(newDuration),
      })
    );
    if (createBookingType.rejected.match(result)) {
      // `payload`, not `error.message` — see the comment on the thunks.
      setCreateError(result.payload ?? 'Failed to create booking type');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewTemplateId('');
    setNewProtection('soft');
    setNewDuration('');
  };

  const handleEditOpen = (row: BookingTypeRecord) => {
    setEditId(row.id);
    setEditName(row.name);
    setEditTemplateId(row.lifecycle_template_id);
    setEditIsActive(row.is_active);
    setEditProtection(row.default_protection_level ?? 'soft');
    setEditDuration(
      row.default_duration_minutes === null || row.default_duration_minutes === undefined
        ? ''
        : String(row.default_duration_minutes)
    );
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
          default_protection_level: editProtection,
          // NOTE: `BookingTypeUpdate` applies every field with
          // `if data.X is not None`, so a null here means "leave alone", not
          // "clear". Blanking this field therefore keeps the existing preset —
          // there is no way through this endpoint to remove one. The helper
          // text below says so rather than letting the user infer it.
          default_duration_minutes: durationToPayload(editDuration),
        },
      })
    );
    if (updateBookingType.rejected.match(result)) {
      setEditError(result.payload ?? 'Failed to update booking type');
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
      setDeleteError(result.payload ?? 'Failed to delete booking type');
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
      field: 'default_protection_level',
      headerName: 'Protection',
      width: 130,
      // A label, not a state: this is the level a NEW request of this type
      // inherits. It gates nothing here and nothing anywhere else (B4 advises).
      renderCell: (params) =>
        PROTECTION_LABELS[params.value as ProtectionLevel] ?? String(params.value ?? ''),
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
          <TextField
            select
            label="Protection"
            value={newProtection}
            onChange={(e) => setNewProtection(e.target.value as ProtectionLevel)}
            helperText="The level a booking of this type inherits. Advisory — it refuses nothing."
          >
            {PROTECTION_LEVELS.map((level) => (
              <MenuItem key={level} value={level}>
                {PROTECTION_LABELS[level]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Default duration (minutes)"
            type="number"
            value={newDuration}
            onChange={(e) => setNewDuration(e.target.value)}
            helperText="Leave blank for no preset. The booking form uses it to fill in the end date."
          />
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
          <TextField
            select
            label="Protection"
            value={editProtection}
            onChange={(e) => setEditProtection(e.target.value as ProtectionLevel)}
            helperText="Applies to bookings made from now on; existing bookings keep their own level."
          >
            {PROTECTION_LEVELS.map((level) => (
              <MenuItem key={level} value={level}>
                {PROTECTION_LABELS[level]}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Default duration (minutes)"
            type="number"
            value={editDuration}
            onChange={(e) => setEditDuration(e.target.value)}
            helperText="Blanking this leaves the existing preset in place — the API cannot clear one."
          />
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
