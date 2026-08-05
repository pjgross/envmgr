import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link as RouterLink, useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchUserGroups,
  createUserGroup,
  updateUserGroup,
  deleteUserGroup,
} from '../../store/userGroupSlice';
import type { UserGroupResponse } from '../../types/userGroup';

// This grid is client-side: no sortingMode="server" or paginationMode="server"
// below, so every click sorts the rows already in the browser and none of it
// reaches the backend. `member_count` and `environment_count` are correlated
// subqueries the backend could never whitelist for server-side sorting (see
// USER_GROUP_SORTS in app/api/v1/user_groups.py) but that doesn't matter here —
// there is no server-side sort to be missing from. `tenant-groups` is
// deliberately absent from sortWhitelists.json and test_sort_whitelist_contract.py
// for exactly this reason (docs/pagination.md's ‡ footnote convention): a
// sortable whitelist entry is only added once a grid actually sorts an
// endpoint server-side.
// eslint-disable-next-line react-refresh/only-export-components
export const userGroupColumns: GridColDef<UserGroupResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'description', headerName: 'Description', flex: 2, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'member_count', headerName: 'Members', width: 110 },
  { field: 'environment_count', headerName: 'Environments', width: 140,
    renderCell: (params) => (
      <Link
        component={RouterLink}
        to={`/environments?operations_group_id=${params.row.id}`}
        onClick={(e) => e.stopPropagation()}
      >
        {params.value}
      </Link>
    ) },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];

export default function UserGroups() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { groups, loading } = useSelector((s: RootState) => s.userGroup);
  // The backend gates POST/PATCH/DELETE on require_tenant_admin(); GET is open
  // to any tenant member (see app/api/v1/user_groups.py). Mirror that split
  // here rather than gating the whole route — PrivateRoute treats a master
  // admin as satisfying any role check, so do the same for the write controls.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<UserGroupResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchUserGroups({}));
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createUserGroup({
        name: newName.trim(),
        description: newDescription.trim() || null,
      })
    );
    if (createUserGroup.rejected.match(result)) {
      setCreateError(result.payload ?? 'Failed to create user group');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewDescription('');
    dispatch(fetchUserGroups({}));
  };

  const openEdit = (row: UserGroupResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditDescription(row.description ?? '');
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateUserGroup({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          description: editDescription.trim() || null,
        },
      })
    );
    if (updateUserGroup.rejected.match(result)) {
      setEditError(result.payload ?? 'Failed to update user group');
      return;
    }
    setEditTarget(null);
    dispatch(fetchUserGroups({}));
  };

  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteUserGroup(deleteId));
    if (deleteUserGroup.rejected.match(result)) {
      // `payload`, not `error.message`. The server's 409 names the environments
      // that block the delete, and that is the entire value of the response —
      // miniSerializeError would replace it with "Request failed with status
      // code 409" and send the admin hunting.
      setDeleteError(result.payload ?? 'Failed to delete user group');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
    // Refetch rather than splicing the row out locally: the list is one
    // server-paged window, and local surgery desynchronises the page from its
    // total once a second page exists.
    dispatch(fetchUserGroups({}));
  };

  const columns: GridColDef<UserGroupResponse>[] = userGroupColumns.map((col) =>
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
        <Typography variant="h5">User Groups</Typography>
        {canWrite && (
          <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
            + New Group
          </Button>
        )}
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        A group organises users for environment access. A group operating
        environments cannot be deleted.
      </Typography>

      <DataGrid
        rows={groups}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        // description/member_count/environment_count are unsortable (see
        // userGroupColumns above); without this a raw DataGrid still offers a
        // Filter menu on them that would silently filter only the fetched
        // window instead of the server-paged set. docs/pagination.md.
        disableColumnFilter
        pageSizeOptions={[10, 25]}
        onRowClick={(params) => navigate(`/tenant/groups/${params.row.id}`)}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New User Group</DialogTitle>
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
        <DialogTitle>Edit User Group</DialogTitle>
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
        <DialogTitle>Delete User Group</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this group? Its members will be removed.
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
