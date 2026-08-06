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
  MenuItem,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';

import type { AppDispatch, RootState } from '../../store';
import { fetchProjects, createProject, updateProject, deleteProject } from '../../store/projectSlice';
import { fetchUserGroups } from '../../store/userGroupSlice';
import type { ProjectResponse } from '../../types/project';

// Sortable fields (whitelist-backed, see the backend's PROJECT_SORTS): `name`,
// `code`, `created_at` ONLY. `team_group_name` is joined and
// `environment_count` is a correlated subquery — neither is backed by a single
// column, so neither can be whitelisted, and a sortable header on them 422s.
// eslint-disable-next-line react-refresh/only-export-components
export const projectColumns: GridColDef<ProjectResponse>[] = [
  { field: 'name', headerName: 'Name', flex: 1 },
  { field: 'code', headerName: 'Code', width: 120,
    renderCell: (params) => (params.value as string | null) ?? '—' },
  { field: 'team_group_name', headerName: 'Team', width: 180, sortable: false,
    renderCell: (params) => (params.value as string | null) ?? '— no team' },
  { field: 'environment_count', headerName: 'Environments', width: 140, sortable: false,
    renderCell: (params) => (
      <Link
        component={RouterLink}
        to={`/environments?project_id=${params.row.id}`}
        onClick={(e) => e.stopPropagation()}
      >
        {params.value}
      </Link>
    ) },
  { field: 'is_active', headerName: 'Status', width: 110, sortable: false,
    renderCell: (params) => (params.value ? 'Active' : 'Archived') },
  { field: 'actions', headerName: '', width: 140, sortable: false, disableColumnMenu: true },
];

export default function Projects() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { projects, loading } = useSelector((s: RootState) => s.project);
  const { groups } = useSelector((s: RootState) => s.userGroup);
  // GET /projects is open to any tenant member — every booking form needs the
  // picker, and everyone needs to see which project a booking belongs to (see
  // app/api/v1/projects.py). POST/PATCH/DELETE are require_tenant_admin().
  // Mirror that split for the write controls, the way UserGroups.tsx does —
  // gating the whole route on B3a's groups was a false analogy caught only by
  // review, and this screen has the identical read/write split.
  const user = useSelector((s: RootState) => s.auth.user);
  const canWrite = user?.role === 'Admin' || user?.is_master_admin === true;

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newCode, setNewCode] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newTeamGroupId, setNewTeamGroupId] = useState<number | ''>('');
  const [createError, setCreateError] = useState<string | null>(null);

  const [editTarget, setEditTarget] = useState<ProjectResponse | null>(null);
  const [editName, setEditName] = useState('');
  const [editCode, setEditCode] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editTeamGroupId, setEditTeamGroupId] = useState<number | ''>('');
  const [editError, setEditError] = useState<string | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchProjects({}));
    // Sourced for the Team picker in the create/edit dialogs below.
    dispatch(fetchUserGroups({}));
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreateError(null);
    const result = await dispatch(
      createProject({
        name: newName.trim(),
        code: newCode.trim() || null,
        description: newDescription.trim() || null,
        team_group_id: newTeamGroupId === '' ? null : Number(newTeamGroupId),
      })
    );
    if (createProject.rejected.match(result)) {
      setCreateError(result.payload ?? 'Failed to create project');
      return;
    }
    setCreateOpen(false);
    setNewName('');
    setNewCode('');
    setNewDescription('');
    setNewTeamGroupId('');
    dispatch(fetchProjects({}));
  };

  const openEdit = (row: ProjectResponse) => {
    setEditTarget(row);
    setEditName(row.name);
    setEditCode(row.code ?? '');
    setEditDescription(row.description ?? '');
    setEditTeamGroupId(row.team_group_id ?? '');
    setEditError(null);
  };

  const handleEditSave = async () => {
    if (!editTarget || !editName.trim()) return;
    setEditError(null);
    const result = await dispatch(
      updateProject({
        id: editTarget.id,
        data: {
          name: editName.trim(),
          code: editCode.trim() || null,
          description: editDescription.trim() || null,
          team_group_id: editTeamGroupId === '' ? null : Number(editTeamGroupId),
        },
      })
    );
    if (updateProject.rejected.match(result)) {
      setEditError(result.payload ?? 'Failed to update project');
      return;
    }
    setEditTarget(null);
    dispatch(fetchProjects({}));
  };

  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteProject(deleteId));
    if (deleteProject.rejected.match(result)) {
      // `payload`, not `error.message` — see the module doc on the slice.
      setDeleteError(result.payload ?? 'Failed to delete project');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
    // Refetch rather than splicing the row out locally: the list is one
    // server-paged window, and local surgery desynchronises the page from its
    // total once a second page exists.
    dispatch(fetchProjects({}));
  };

  const columns: GridColDef<ProjectResponse>[] = projectColumns.map((col) =>
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
        <Typography variant="h5">Projects</Typography>
        {canWrite && (
          <Button variant="contained" size="small" onClick={() => setCreateOpen(true)}>
            + New Project
          </Button>
        )}
      </Box>
      <Typography color="text.secondary" sx={{ mb: 2 }}>
        A project coordinates work across releases, bookings and environments.
      </Typography>

      <DataGrid
        rows={projects}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        // team_group_name/environment_count/is_active/actions are unsortable
        // (see projectColumns above); without this a raw DataGrid still offers
        // a Filter menu on them that would silently filter only the fetched
        // window instead of the server-paged set. docs/pagination.md.
        disableColumnFilter
        pageSizeOptions={[10, 25]}
        onRowClick={(params) => navigate(`/tenant/projects/${params.row.id}`)}
      />

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Project</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createError && <Alert severity="error">{createError}</Alert>}
          <TextField
            label="Name"
            required
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <TextField label="Code" value={newCode} onChange={(e) => setNewCode(e.target.value)} />
          <TextField
            label="Description"
            multiline
            minRows={2}
            value={newDescription}
            onChange={(e) => setNewDescription(e.target.value)}
          />
          <TextField
            select
            label="Team"
            value={newTeamGroupId}
            onChange={(e) => setNewTeamGroupId(e.target.value ? Number(e.target.value) : '')}
          >
            <MenuItem value="">— no team</MenuItem>
            {groups.map((g) => (
              <MenuItem key={g.id} value={g.id}>
                {g.name}
              </MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={!newName.trim()}>
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(editTarget)} onClose={() => setEditTarget(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit Project</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {editError && <Alert severity="error">{editError}</Alert>}
          <TextField
            label="Name"
            required
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
          />
          <TextField label="Code" value={editCode} onChange={(e) => setEditCode(e.target.value)} />
          <TextField
            label="Description"
            multiline
            minRows={2}
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
          />
          <TextField
            select
            label="Team"
            value={editTeamGroupId}
            onChange={(e) => setEditTeamGroupId(e.target.value ? Number(e.target.value) : '')}
          >
            <MenuItem value="">— no team</MenuItem>
            {groups.map((g) => (
              <MenuItem key={g.id} value={g.id}>
                {g.name}
              </MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditTarget(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave} disabled={!editName.trim()}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Project</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this project? Its usage agreements will be
            removed; bookings and releases that reference it keep their history.
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
