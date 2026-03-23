import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link } from 'react-router-dom'
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
} from '@mui/material'
import { fetchTenants, createTenant, disableTenant, signInAsTenant } from '../../store/adminSlice'
import type { RootState, AppDispatch } from '../../store'

export default function TenantList() {
  const dispatch = useDispatch<AppDispatch>()
  const { tenants, loading, error } = useSelector((state: RootState) => state.admin)

  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [formError, setFormError] = useState('')

  useEffect(() => {
    dispatch(fetchTenants())
  }, [dispatch])

  const handleCreate = async () => {
    if (!newName.trim() || !newSlug.trim()) {
      setFormError('Name and slug are required')
      return
    }
    try {
      await dispatch(createTenant({ name: newName.trim(), slug: newSlug.trim() })).unwrap()
      setCreateOpen(false)
      setNewName('')
      setNewSlug('')
      setFormError('')
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create tenant')
    }
  }

  const handleDisable = async (id: number) => {
    if (window.confirm('Disable this tenant? All users will lose access.')) {
      try {
        await dispatch(disableTenant(id)).unwrap()
      } catch {
        alert('Failed to disable tenant')
      }
    }
  }

  const handleSignInAs = async (id: number) => {
    try {
      await dispatch(signInAsTenant(id)).unwrap()
    } catch {
      alert('Failed to sign in as tenant')
    }
  }

  return (
    <Box sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h5">Tenants</Typography>
          <Button variant="contained" onClick={() => setCreateOpen(true)}>
            New Tenant
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
                  <TableCell>Name</TableCell>
                  <TableCell>Slug</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell>Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {tenants.map((tenant) => (
                  <TableRow key={tenant.id}>
                    <TableCell>
                      <Link to={`/admin/tenants/${tenant.id}`}>{tenant.name}</Link>
                    </TableCell>
                    <TableCell>{tenant.slug}</TableCell>
                    <TableCell>
                      <Chip
                        label={tenant.is_active ? 'Active' : 'Disabled'}
                        color={tenant.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>{new Date(tenant.created_at).toLocaleDateString()}</TableCell>
                    <TableCell>
                      <Button
                        size="small"
                        variant="outlined"
                        sx={{ mr: 1 }}
                        onClick={() => handleSignInAs(tenant.id)}
                      >
                        Sign In As
                      </Button>
                      {tenant.is_active && (
                        <Button
                          size="small"
                          variant="outlined"
                          color="error"
                          onClick={() => handleDisable(tenant.id)}
                        >
                          Disable
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {tenants.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">No tenants found</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Paper>
        )}

        <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
          <DialogTitle>Create Tenant</DialogTitle>
          <DialogContent>
            {formError && <Alert severity="error" sx={{ mb: 2 }}>{formError}</Alert>}
            <TextField
              label="Name"
              fullWidth
              margin="normal"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <TextField
              label="Slug"
              fullWidth
              margin="normal"
              value={newSlug}
              onChange={(e) => setNewSlug(e.target.value)}
              helperText="URL-friendly identifier (e.g. acme-corp)"
            />
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button variant="contained" onClick={handleCreate}>Create</Button>
          </DialogActions>
        </Dialog>
    </Box>
  )
}
