import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
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
  AppBar,
  Toolbar,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from '@mui/material'
import { fetchTenantUsers, createTenantUser } from '../../store/adminSlice'
import type { RootState, AppDispatch } from '../../store'

export default function TenantDetail() {
  const { tenantId } = useParams<{ tenantId: string }>()
  const id = Number(tenantId)
  const dispatch = useDispatch<AppDispatch>()
  const { tenantUsers, tenants, loading, error } = useSelector((state: RootState) => state.admin)
  const tenant = tenants.find(t => t.id === id)

  const [createOpen, setCreateOpen] = useState(false)
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('Member')
  const [formError, setFormError] = useState('')

  useEffect(() => {
    if (id) {
      dispatch(fetchTenantUsers(id))
    }
  }, [dispatch, id])

  const handleCreateUser = async () => {
    if (!username.trim() || !email.trim() || !password.trim()) {
      setFormError('Username, email, and password are required')
      return
    }
    try {
      await dispatch(createTenantUser({ tenantId: id, data: { username: username.trim(), email: email.trim(), password, role } })).unwrap()
      setCreateOpen(false)
      setUsername('')
      setEmail('')
      setPassword('')
      setRole('Member')
      setFormError('')
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create user')
    }
  }

  return (
    <Box>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            Platform Admin — Tenant Detail
          </Typography>
          <Button color="inherit" component={Link} to="/admin/tenants">
            Back to Tenants
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ p: 3 }}>
        {tenant && (
          <Box sx={{ mb: 3 }}>
            <Typography variant="h5">{tenant.name}</Typography>
            <Typography variant="body2" color="text.secondary">Slug: {tenant.slug}</Typography>
            <Chip
              label={tenant.is_active ? 'Active' : 'Disabled'}
              color={tenant.is_active ? 'success' : 'default'}
              size="small"
              sx={{ mt: 1 }}
            />
          </Box>
        )}

        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Users</Typography>
          <Button variant="contained" onClick={() => setCreateOpen(true)}>
            Create User
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
                  <TableCell>Created</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tenantUsers.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>{user.username}</TableCell>
                    <TableCell>{user.email}</TableCell>
                    <TableCell>{user.role}</TableCell>
                    <TableCell>
                      <Chip
                        label={user.is_active ? 'Active' : 'Inactive'}
                        color={user.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                  </TableRow>
                ))}
                {tenantUsers.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">No users found</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        )}

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
              <InputLabel>Role</InputLabel>
              <Select value={role} label="Role" onChange={(e) => setRole(e.target.value)}>
                <MenuItem value="Member">Member</MenuItem>
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
    </Box>
  )
}
