import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Typography,
  Table,
  TableContainer,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  Chip,
  Button,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Paper,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  FormControlLabel,
  Checkbox,
} from '@mui/material';
import {
  fetchTenantUsers,
  createTenantUser,
  updateTenantUser,
  setTenantUserRole,
  deactivateTenantUser,
  reactivateTenantUser,
  resetUserPassword,
} from '../../store/adminSlice';
import type { UserResponse } from '../../types';
import type { RootState, AppDispatch } from '../../store';
import { useSnackbar } from '../../hooks/useSnackbar';
import DetailPageHeader from '../../components/layout/DetailPageHeader';
import { useConfirm } from '../../hooks/useConfirm';

export default function TenantDetail() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const id = Number(tenantId);
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const { tenantUsers, tenants, loading, error } = useSelector((state: RootState) => state.admin);
  const tenant = tenants.find((t) => t.id === id);

  const [createOpen, setCreateOpen] = useState(false);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState('Viewer');
  const [isMasterAdmin, setIsMasterAdmin] = useState(false);
  const [formError, setFormError] = useState('');

  const [editUser, setEditUser] = useState<UserResponse | null>(null);
  const [editUsername, setEditUsername] = useState('');
  const [editEmail, setEditEmail] = useState('');
  const [editIsMasterAdmin, setEditIsMasterAdmin] = useState(false);
  const [editNewPassword, setEditNewPassword] = useState('');
  const [editError, setEditError] = useState('');

  useEffect(() => {
    if (id) {
      dispatch(fetchTenantUsers(id));
    }
  }, [dispatch, id]);

  const openEdit = (user: UserResponse) => {
    setEditUser(user);
    setEditUsername(user.username);
    setEditEmail(user.email);
    setEditIsMasterAdmin(user.is_master_admin);
    setEditNewPassword('');
    setEditError('');
  };

  const handleEditSave = async () => {
    if (!editUser) return;
    if (!editUsername.trim() || !editEmail.trim()) {
      setEditError('Username and email are required');
      return;
    }
    if (editNewPassword && editNewPassword.length < 8) {
      setEditError('New password must be at least 8 characters');
      return;
    }
    try {
      await dispatch(
        updateTenantUser({
          tenantId: id,
          userId: editUser.id,
          data: {
            username: editUsername.trim(),
            email: editEmail.trim(),
            is_master_admin: editIsMasterAdmin,
          },
        })
      ).unwrap();
      if (editNewPassword) {
        await dispatch(
          resetUserPassword({ tenantId: id, userId: editUser.id, newPassword: editNewPassword })
        ).unwrap();
      }
      setEditUser(null);
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Failed to update user');
    }
  };

  const handleRoleChange = async (userId: number, newRole: string) => {
    try {
      await dispatch(setTenantUserRole({ tenantId: id, userId, role: newRole })).unwrap();
    } catch {
      snackbar.error('Failed to update role');
    }
  };

  const handleDeactivate = async (user: UserResponse) => {
    const label = user.username ? user.username : 'this user';
    if (
      await confirm({
        message: `Deactivate ${label}? They will lose access immediately.`,
        destructive: true,
      })
    ) {
      try {
        await dispatch(deactivateTenantUser({ tenantId: id, userId: user.id })).unwrap();
      } catch {
        snackbar.error('Failed to deactivate user');
      }
    }
  };

  const handleReactivate = async (userId: number) => {
    try {
      await dispatch(reactivateTenantUser({ tenantId: id, userId })).unwrap();
    } catch {
      snackbar.error('Failed to reactivate user');
    }
  };

  const handleCreateUser = async () => {
    if (!username.trim() || !email.trim() || !password.trim()) {
      setFormError('Username, email, and password are required');
      return;
    }
    try {
      await dispatch(
        createTenantUser({
          tenantId: id,
          data: {
            username: username.trim(),
            email: email.trim(),
            password,
            role,
            is_master_admin: isMasterAdmin,
          },
        })
      ).unwrap();
      setCreateOpen(false);
      setUsername('');
      setEmail('');
      setPassword('');
      setRole('Viewer');
      setIsMasterAdmin(false);
      setFormError('');
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create user');
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <DetailPageHeader
        back={{ to: '/admin/tenants', label: 'Tenants' }}
        title={tenant?.name}
        status={
          tenant && (
            <Chip
              label={tenant.is_active ? 'Active' : 'Disabled'}
              color={tenant.is_active ? 'success' : 'default'}
              size="small"
            />
          )
        }
      />
      {tenant && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Slug: {tenant.slug}
        </Typography>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
        <Typography variant="h6">Users</Typography>
        <Button variant="contained" onClick={() => setCreateOpen(true)}>
          Create User
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : (
        <Paper>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Username</TableCell>
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tenantUsers.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>{user.username}</TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>
                      <FormControl size="small" disabled={!user.is_active}>
                        <Select
                          value={user.role}
                          onChange={(e) => handleRoleChange(user.id, e.target.value)}
                        >
                          <MenuItem value="Viewer">Viewer</MenuItem>
                          <MenuItem value="Developer">Developer</MenuItem>
                          <MenuItem value="Test Manager">Test Manager</MenuItem>
                          <MenuItem value="Release Manager">Release Manager</MenuItem>
                          <MenuItem value="Admin">Admin</MenuItem>
                        </Select>
                      </FormControl>
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={user.is_active ? 'Active' : 'Inactive'}
                        color={user.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                    <TableCell>
                      <Button
                        size="small"
                        variant="outlined"
                        sx={{ mr: 1 }}
                        onClick={() => openEdit(user)}
                      >
                        Edit
                      </Button>
                      {user.is_active ? (
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          onClick={() => handleDeactivate(user)}
                        >
                          Deactivate
                        </Button>
                      ) : (
                        <Button
                          size="small"
                          variant="outlined"
                          color="success"
                          onClick={() => handleReactivate(user.id)}
                        >
                          Reactivate
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {tenantUsers.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} align="center">
                      No users found
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      )}

      {confirmDialog}
      <Dialog open={Boolean(editUser)} onClose={() => setEditUser(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Edit User</DialogTitle>
        <DialogContent>
          {editError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {editError}
            </Alert>
          )}
          <TextField
            label="Username"
            fullWidth
            margin="normal"
            value={editUsername}
            onChange={(e) => setEditUsername(e.target.value)}
          />
          <TextField
            label="Email"
            fullWidth
            margin="normal"
            type="email"
            value={editEmail}
            onChange={(e) => setEditEmail(e.target.value)}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={editIsMasterAdmin}
                onChange={(e) => setEditIsMasterAdmin(e.target.checked)}
              />
            }
            label="Master Admin (cross-tenant access)"
            sx={{ mt: 1 }}
          />
          <TextField
            label="New Password (leave blank to keep current)"
            fullWidth
            margin="normal"
            type="password"
            value={editNewPassword}
            onChange={(e) => setEditNewPassword(e.target.value)}
            helperText="Minimum 8 characters"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditUser(null)}>Cancel</Button>
          <Button variant="contained" onClick={handleEditSave}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create User</DialogTitle>
        <DialogContent>
          {formError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {formError}
            </Alert>
          )}
          <TextField
            label="Username"
            fullWidth
            margin="normal"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <TextField
            label="Email"
            fullWidth
            margin="normal"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <TextField
            label="Password"
            fullWidth
            margin="normal"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <FormControl fullWidth margin="normal">
            <InputLabel>Role</InputLabel>
            <Select value={role} label="Role" onChange={(e) => setRole(e.target.value)}>
              <MenuItem value="Viewer">Viewer</MenuItem>
              <MenuItem value="Developer">Developer</MenuItem>
              <MenuItem value="Test Manager">Test Manager</MenuItem>
              <MenuItem value="Release Manager">Release Manager</MenuItem>
              <MenuItem value="Admin">Admin</MenuItem>
            </Select>
          </FormControl>
          <FormControlLabel
            control={
              <Checkbox
                checked={isMasterAdmin}
                onChange={(e) => setIsMasterAdmin(e.target.checked)}
              />
            }
            label="Master Admin (cross-tenant access)"
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
          <Button variant="contained" onClick={handleCreateUser}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
