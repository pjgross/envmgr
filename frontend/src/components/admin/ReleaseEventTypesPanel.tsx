/**
 * ReleaseEventTypesPanel — admin DataGrid for release event types.
 * System types (is_system=true) show a lock icon; name is read-only and delete is refused.
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import LockIcon from '@mui/icons-material/Lock';
import type { GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import { AppDispatch, RootState } from '../../store';
import {
  fetchReleaseEventTypes,
  createReleaseEventType,
  updateReleaseEventType,
  deleteReleaseEventType,
} from '../../store/releaseEventTypeSlice';
import type {
  ReleaseEventTypeResponse,
  ReleaseEventTypeCreatePayload,
} from '../../types/releaseEvent';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';

interface FormState {
  name: string;
  display_color: string;
}

const DEFAULT_FORM: FormState = { name: '', display_color: '' };

export default function ReleaseEventTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const { list, loading } = useSelector((s: RootState) => s.releaseEventType);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ReleaseEventTypeResponse | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [saving, setSaving] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchReleaseEventTypes());
  }, [dispatch]);

  const openNew = () => {
    setEditTarget(null);
    setForm(DEFAULT_FORM);
    setDeleteError(null);
    setDialogOpen(true);
  };

  const openEdit = (row: ReleaseEventTypeResponse) => {
    setEditTarget(row);
    setForm({ name: row.name, display_color: row.display_color ?? '' });
    setDeleteError(null);
    setDialogOpen(true);
  };

  const handleClose = () => {
    setDialogOpen(false);
    setEditTarget(null);
    setDeleteError(null);
  };

  const handleSave = async () => {
    if (!form.name.trim()) return;
    setSaving(true);
    try {
      const payload: ReleaseEventTypeCreatePayload = {
        name: form.name.trim(),
        display_color: form.display_color.trim() || null,
      };
      if (editTarget) {
        await dispatch(updateReleaseEventType({ id: editTarget.id, data: payload })).unwrap();
        snackbar.success('Event type updated');
      } else {
        await dispatch(createReleaseEventType(payload)).unwrap();
        snackbar.success('Event type created');
      }
      handleClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save event type');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (row: ReleaseEventTypeResponse) => {
    if (row.is_system) {
      setDeleteError(`"${row.name}" is a system event type and cannot be deleted.`);
      return;
    }
    if (!(await confirm({ message: `Delete event type "${row.name}"?`, destructive: true }))) return;
    try {
      await dispatch(deleteReleaseEventType(row.id)).unwrap();
      snackbar.success('Event type deleted');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete event type');
    }
  };

  const columns: GridColDef[] = [
    {
      field: 'name',
      headerName: 'Name',
      flex: 1,
      minWidth: 160,
      renderCell: (params: GridRenderCellParams<ReleaseEventTypeResponse>) => (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          {params.row.is_system && (
            <Tooltip title="System type — name is read-only">
              <LockIcon fontSize="small" color="action" />
            </Tooltip>
          )}
          <Typography variant="body2">{params.row.name}</Typography>
        </Box>
      ),
    },
    {
      field: 'display_color',
      headerName: 'Colour',
      width: 120,
      renderCell: (params: GridRenderCellParams<ReleaseEventTypeResponse>) =>
        params.row.display_color ? (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box
              sx={{
                width: 16,
                height: 16,
                borderRadius: '50%',
                bgcolor: params.row.display_color,
                border: 1,
                borderColor: 'divider',
              }}
            />
            <Typography variant="body2">{params.row.display_color}</Typography>
          </Box>
        ) : (
          <Typography variant="body2" color="text.secondary">
            —
          </Typography>
        ),
    },
    {
      field: 'is_system',
      headerName: 'System',
      width: 90,
      renderCell: (params: GridRenderCellParams<ReleaseEventTypeResponse>) =>
        params.row.is_system ? 'Yes' : 'No',
    },
    {
      field: 'actions',
      headerName: '',
      width: 100,
      sortable: false,
      filterable: false,
      renderCell: (params: GridRenderCellParams<ReleaseEventTypeResponse>) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="Edit">
            <IconButton size="small" onClick={() => openEdit(params.row)}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title={params.row.is_system ? 'System types cannot be deleted' : 'Delete'}>
            <span>
              <IconButton
                size="small"
                color="error"
                onClick={() => handleDelete(params.row)}
                disabled={params.row.is_system}
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        </Box>
      ),
    },
  ];

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
        <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
          Release Event Types
        </Typography>
        <Button size="small" variant="outlined" startIcon={<AddIcon />} onClick={openNew}>
          Add Type
        </Button>
      </Box>

      {deleteError && (
        <Alert severity="warning" onClose={() => setDeleteError(null)} sx={{ mb: 2 }}>
          {deleteError}
        </Alert>
      )}

      <DataTable
        storageKey="admin-release-event-types"
        emptyMessage="No release event types configured yet."
        rows={list}
        columns={columns}
        loading={loading}
        autoHeight
        pageSizeOptions={[25]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        disableRowSelectionOnClick
        sx={{ bgcolor: 'background.paper' }}
      />

      {confirmDialog}
      <Dialog open={dialogOpen} onClose={handleClose} maxWidth="xs" fullWidth>
        <DialogTitle>{editTarget ? 'Edit Event Type' : 'New Event Type'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Name"
              required
              fullWidth
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              disabled={editTarget?.is_system ?? false}
              helperText={editTarget?.is_system ? 'System type names are read-only' : undefined}
            />
            <TextField
              label="Display Colour (CSS colour)"
              fullWidth
              value={form.display_color}
              onChange={(e) => setForm((f) => ({ ...f, display_color: e.target.value }))}
              placeholder="#1976d2"
              InputProps={{
                endAdornment: form.display_color ? (
                  <Box
                    sx={{
                      width: 20,
                      height: 20,
                      borderRadius: '50%',
                      bgcolor: form.display_color,
                      border: 1,
                      borderColor: 'divider',
                      mr: 1,
                      flexShrink: 0,
                    }}
                  />
                ) : null,
              }}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={saving || !form.name.trim()}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
