import { useCallback, useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Link } from 'react-router-dom';
import {
  Box,
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
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import { fetchTenants, createTenant, disableTenant, signInAsTenant } from '../../store/adminSlice';
import type { RootState, AppDispatch } from '../../store';
import DataTable from '../../components/DataTable';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import PageHeader from '../../components/layout/PageHeader';

interface TenantRow {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  created_at: string;
}

export default function TenantList() {
  const dispatch = useDispatch<AppDispatch>();
  const { tenants, loading, error } = useSelector((state: RootState) => state.admin);
  const currentUserId = useSelector((state: RootState) => state.auth.user?.id);
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newSlug, setNewSlug] = useState('');
  const [formError, setFormError] = useState('');

  useEffect(() => {
    dispatch(fetchTenants());
  }, [dispatch]);

  const handleCreate = async () => {
    if (!newName.trim() || !newSlug.trim()) {
      setFormError('Name and slug are required');
      return;
    }
    try {
      await dispatch(createTenant({ name: newName.trim(), slug: newSlug.trim() })).unwrap();
      setCreateOpen(false);
      setNewName('');
      setNewSlug('');
      setFormError('');
      snackbar.success('Tenant created');
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : 'Failed to create tenant');
    }
  };

  const handleDisable = useCallback(
    async (tenant: TenantRow) => {
      const label = tenant.name ? `tenant "${tenant.name}"` : 'this tenant';
      if (
        await confirm({
          message: `Disable ${label}? All its users will lose access.`,
          destructive: true,
        })
      ) {
        try {
          await dispatch(disableTenant(tenant.id)).unwrap();
          snackbar.success('Tenant disabled');
        } catch {
          snackbar.error('Failed to disable tenant');
        }
      }
    },
    [dispatch, snackbar, confirm]
  );

  const handleSignInAs = useCallback(
    async (id: number) => {
      try {
        await dispatch(signInAsTenant(id)).unwrap();
      } catch {
        snackbar.error('Failed to sign in as tenant');
      }
    },
    [dispatch, snackbar]
  );

  const columns = useMemo<GridColDef<TenantRow>[]>(
    () => [
      {
        field: 'name',
        headerName: 'Name',
        flex: 1,
        minWidth: 160,
        renderCell: (params) => (
          <Link to={`/admin/tenants/${params.row.id}`}>{params.row.name}</Link>
        ),
      },
      { field: 'slug', headerName: 'Slug', flex: 1, minWidth: 140 },
      {
        field: 'is_active',
        headerName: 'Status',
        width: 120,
        sortable: true,
        renderCell: (params) => (
          <Chip
            label={params.row.is_active ? 'Active' : 'Disabled'}
            color={params.row.is_active ? 'success' : 'default'}
            size="small"
          />
        ),
      },
      {
        field: 'created_at',
        headerName: 'Created',
        width: 140,
        valueGetter: (params) => new Date(params.row.created_at),
        valueFormatter: (params) =>
          params.value instanceof Date ? params.value.toLocaleDateString() : '',
      },
      {
        field: 'actions',
        headerName: 'Actions',
        width: 220,
        sortable: false,
        filterable: false,
        renderCell: (params) => (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button size="small" variant="outlined" onClick={() => handleSignInAs(params.row.id)}>
              Sign In As
            </Button>
            {params.row.is_active && (
              <Button
                size="small"
                variant="outlined"
                color="error"
                onClick={() => handleDisable(params.row)}
              >
                Disable
              </Button>
            )}
          </Box>
        ),
      },
    ],
    [handleDisable, handleSignInAs]
  );

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Tenants"
        actions={
          <Button variant="contained" onClick={() => setCreateOpen(true)}>
            New Tenant
          </Button>
        }
      />

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <CircularProgress />
      ) : (
        <Paper sx={{ height: 600, width: '100%' }}>
          <DataTable<TenantRow>
            storageKey="admin-tenants-columns"
            userId={currentUserId}
            rows={tenants}
            columns={columns}
            emptyMessage="No tenants found"
            disableColumnMenu={false}
          />
        </Paper>
      )}

      {confirmDialog}
      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Create Tenant</DialogTitle>
        <DialogContent>
          {formError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {formError}
            </Alert>
          )}
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
          <Button variant="contained" onClick={handleCreate}>
            Create
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
