import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import {
  Box,
  Typography,
  Table,
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
} from '@mui/material'
import { fetchUsers, createUser, updateUser, setUserRole, deactivateUser, reactivateUser } from '../../store/tenantAdminSlice'
import type { UserResponse } from '../../types'
import type { RootState, AppDispatch } from '../../store'

export default function UserManagement() {
  const dispatch = useDispatch<AppDispatch>()
  const { users, loading, error } = useSelector((state: RootState) => state.tenantAdmin)

  const [createOpen, setCreateOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('Viewer')
  const [formError, setFormError] = useState('')

  const [editUser, setEditUser] = useState<UserResponse | null>(null)
  const [editUsername, setEditUsername] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editError, setEditError] = useState('')

  useEffect(() => {
    dispatch(fetchUsers())
  }, [dispatch])

  const handleCreateUser = async () => {
    if (!username.trim() || !email.trim() || !password.trim()) {
      setFormError('Username, email, and password are required')
      return
    }
    try {
      await dispatch(createUser({ username: username.trim(), email: email.trim(), password, role })).unwrap()
      setCreateOpen(false)
      setUsername('')
      setEmail('')
      setPassword('')
      setRole('Viewer')
      setFormError('')
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create user')
    }
  }

  const openEdit = (user: UserResponse) => {
    setEditUser(user)
    setEditUsername(user.username)
    setEditEmail(user.email)
    setEditError('')
  }

  const handleEditSave = async () => {
    if (!editUser) return
    if (!editUsername.trim() || !editEmail.trim()) {
      setEditError('Username and email are required')
      return
    }
    try {
      await dispatch(updateUser({ id: editUser.id, data: { username: editUsername.trim(), email: editEmail.trim() } })).unwrap()
      setEditUser(null)
    } catch (err: unknown) {
      setEditError(err instanceof Error ? err.message : 'Failed to update user')
    }
  }

  const handleRoleChange = async (id: number, newRole: string) => {
    try {
      await dispatch(setUserRole({ id, role: newRole })).unwrap()
    } catch {
      alert('Failed to update role')
    }
  }

  const handleDeactivate = (id: number) => {
    if (window.confirm('Deactivate this user?')) {
      dispatch(deactivateUser(id))
    }
  }

  const handleReactivate = (id: number) => {
    dispatch(reactivateUser(id))
  }

  return (
    <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h5">Users</Typography>
          <Button variant="contained" onClick={() => setCreateOpen(true)}>
            New User
          </Button>
        </Box>

        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        {loading ? (
          <CircularProgress />
        ) : (
          <Paper>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Username</TableCell>
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((user) => (
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
                    <TableCell>
                      <Button size="small" variant="outlined" sx={{ mr: 1 }} onClick={() => openEdit(user)}>Edit</Button>
                      {user.is_active ? (
                        <Button size="small" variant="outlined" color="error" onClick={() => handleDeactivate(user.id)}>Deactivate</Button>
                      ) : (
                        <Button size="small" variant="outlined" color="success" onClick={() => handleReactivate(user.id)}>Reactivate</Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {users.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">No users found</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        )}

        <Dialog open={Boolean(editUser)} onClose={() => setEditUser(null)} maxWidth="sm" fullWidth>
          <DialogTitle>Edit User</DialogTitle>
          <DialogContent>
            {editError && <Alert severity="error" sx={{ mb: 2 }}>{editError}</Alert>}
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
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setEditUser(null)}>Cancel</Button>
            <Button variant="contained" onClick={handleEditSave}>Save</Button>
          </DialogActions>
        </Dialog>

        <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Create User</DialogTitle>
          <DialogContent>
            {formError && <Alert severity="error" sx={{ mb: 2 }}>{formError}</Alert>}
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
              <Select value={role} onChange={(e) => setRole(e.target.value)}>
                <MenuItem value="Viewer">Viewer</MenuItem>
                <MenuItem value="Developer">Developer</MenuItem>
                <MenuItem value="Test Manager">Test Manager</MenuItem>
                <MenuItem value="Release Manager">Release Manager</MenuItem>
                <MenuItem value="Admin">Admin</MenuItem>
              </Select>
            </FormControl>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button variant="contained" onClick={handleCreateUser}>Create</Button>
          </DialogActions>
        </Dialog>
    </Box>
  )
}
