import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchEnvironmentGroups,
  createEnvironmentGroup,
  updateEnvironmentGroup,
  deleteEnvironmentGroup,
} from '../../store/environmentGroupSlice';
import type { EnvironmentGroupResponse } from '../../types/environmentGroup';

// Sortable fields (whitelist-backed, see ENVIRONMENT_GROUP_SORTS): `name` and
// `created_at` ONLY. `member_count` is a correlated subquery — not backed by a
// single column, so it can never be whitelisted, and a sortable header on it
// sends a sort_by the backend answers with 422.
//
// This grid is client-side (no sortingMode="server" / paginationMode="server"),
// matching UserGroups.tsx and Projects.tsx: a tenant's group list is small and
// bounded by configuration. `tenant-environment-groups` is therefore absent
// from sortWhitelists.json, the same ‡ convention docs/pagination.md records.
// eslint-disable-next-line react-refresh/only-export-components
export const environmentGroupColumns: GridColDef<EnvironmentGroupResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'description', headerName: 'Description', flex: 1, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'member_count', headerName: 'Environments', width: 140, sortable: false },
  { field: 'is_active', headerName: 'Status', width: 110, sortable: false,
    renderCell: (params) => (params.value ? 'Active' : 'Archived') },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];

export default function EnvironmentGroups() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { groups, loading } = useSelector((s: RootState) => s.environmentGroup);
  // GET /environment-groups is open to any tenant member — every booking form
  // needs the group picker, and everyone needs to see which group a booking
  // belongs to. POST/PATCH/DELETE are require_tenant_admin(). Mirror the split
  // Projects.tsx and UserGroups.tsx use for their write controls.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<EnvironmentGroupResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchEnvironmentGroups({}));
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createEnvironmentGroup({
        name: newName.trim(),
        description: newDescription.trim() || null,
      })
    );
    if (createEnvironmentGroup.rejected.match(result)) {
      setCreateError(result.payload ?? 'Failed to create environment group');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewDescription('');
    dispatch(fetchEnvironmentGroups({}));
  };

  const openEdit = (row: EnvironmentGroupResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditDescription(row.description ?? '');
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateEnvironmentGroup({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          description: editDescription.trim() || null,
        },
      })
    );
    if (updateEnvironmentGroup.rejected.match(result)) {
      // `payload`, not `error.message` — see the slice's module docblock.
      setEditError(result.payload ?? 'Failed to update environment group');
      return;
    }
    setEditTarget(null);
    dispatch(fetchEnvironmentGroups({}));
  };

  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteEnvironmentGroup(deleteId));
    if (deleteEnvironmentGroup.rejected.match(result)) {
      setDeleteError(result.payload ?? 'Failed to delete environment group');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
    // Refetch rather than splicing the row out locally: the slice deliberately
    // has no fulfilled handler for delete (see environmentGroupSlice.ts), and
    // local surgery would desynchronise the page from its total once a second
    // page exists.
    dispatch(fetchEnvironmentGroups({}));
  };

  const columns: GridColDef<EnvironmentGroupResponse>[] = environmentGroupColumns.map((col) =>
    col.field === 'actions'
      ? {
          ...col,
          renderCell: (params) =>
            canWrite ? (
              <Box sx={{ display: 'flex', gap: 0.5 }}>
                <Button
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    openEdit(params.row);
                  }}
                >
                  Edit
                </Button>
                <Button
                  size="small"
                  color="error"
                  onClick={(e) => {
                    e.stopPropagation();
                    setDeleteError(null);
                    setDeleteId(params.row.id);
                    setDeleteOpen(true);
                  }}
                >
                  Delete
                </Button>
              </Box>
            ) : null,
        }
      : col
  );

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h5">Environment Groups</Typography>
        {canWrite && (
          <Button
            variant="contained"
            size="small"
            onClick={() => {
              // Reset the dialog's own error before it opens, or a previous
              // failure's message greets a fresh, untouched form (the bug
              // Projects.tsx fixed and UserGroups.tsx still carries).
              setCreateError(null);
              setCreateOpen(true);
            }}
          >
            + New Group
          </Button>
        )}
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        An environment group is a named set of environments bookable as one unit;
        member bookings transition together.
      </Typography>

      <DataGrid
        rows={groups}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        // description/member_count/is_active/actions are unsortable (see
        // environmentGroupColumns above); without this a raw DataGrid still
        // offers a Filter menu on them that would silently filter only the
        // fetched window instead of the server-paged set. docs/pagination.md.
        disableColumnFilter
        pageSizeOptions={[10, 25]}
        onRowClick={(params) => navigate(`/environment-groups/${params.row.id}`)}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Environment Group</DialogTitle>
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
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onClose={() => setEditTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Environment Group</DialogTitle>
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
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave} disabled={!editName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Environment Group</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this environment group? Its membership
            records will be removed; bookings made through it keep their history.
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
