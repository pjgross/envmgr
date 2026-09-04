import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box, Button, Chip, IconButton, Paper, Stack, Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { DataGrid, GridColDef, GridRenderCellParams, GridValueGetterParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  clearJustCreated,
  createApiKey,
  fetchApiKeys,
  revokeApiKey,
} from '../../store/apiKeySlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import { useConfirm } from '../../hooks/useConfirm';
import ApiKeyCreateDialog from '../../components/apikeys/ApiKeyCreateDialog';
import ApiKeyCreatedDialog from '../../components/apikeys/ApiKeyCreatedDialog';
import type { ApiKey, ApiKeyCreatePayload } from '../../types/apiKey';
import PageHeader from '../../components/layout/PageHeader';

export default function ApiKeyManagement() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const { items, justCreated, loading } = useSelector((s: RootState) => s.apiKey);

  const [createOpen, setCreateOpen] = useState(false);

  useEffect(() => {
    dispatch(fetchApiKeys());
  }, [dispatch]);

  const handleCreate = async (data: ApiKeyCreatePayload) => {
    try {
      await dispatch(createApiKey(data)).unwrap();
      snackbar.success('API key created');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create API key');
    }
  };

  const handleRevoke = async (key: ApiKey) => {
    const label = key.name ? `API key "${key.name}"` : 'this API key';
    if (
      !(await confirm({
        message: `Revoke ${label}? Anything using it will stop working.`,
        destructive: true,
      }))
    )
      return;
    try {
      await dispatch(revokeApiKey(key.id)).unwrap();
      snackbar.success('API key revoked');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to revoke API key');
    }
  };

  const cols: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'scopes', headerName: 'Scopes', flex: 1,
      renderCell: (p: GridRenderCellParams) => (
        <Stack direction="row" spacing={0.5}>
          {(p.value as string[]).map((s) => (
            <Chip key={s} label={s} size="small" variant="outlined" />
          ))}
        </Stack>
      ),
    },
    { field: 'created_by_username', headerName: 'Created by', width: 140 },
    {
      field: 'last_used_at', headerName: 'Last used', width: 180,
      valueGetter: (params: GridValueGetterParams) =>
        params.row.last_used_at ? new Date(params.row.last_used_at).toLocaleString() : '—',
    },
    {
      field: 'expires_at', headerName: 'Expires', width: 140,
      valueGetter: (params: GridValueGetterParams) =>
        params.row.expires_at ? new Date(params.row.expires_at).toLocaleDateString() : 'Never',
    },
    {
      field: 'actions', headerName: '', width: 80, sortable: false,
      renderCell: (p) => (
        <Tooltip title="Revoke">
          <IconButton size="small" color="error" onClick={() => handleRevoke(p.row)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="API keys"
        actions={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            New key
          </Button>
        }
      />

      <Paper variant="outlined">
        <DataGrid
          rows={items}
          columns={cols}
          autoHeight
          loading={loading}
          disableRowSelectionOnClick
        />
      </Paper>

      <ApiKeyCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onSubmit={handleCreate}
      />

      {justCreated && (
        <ApiKeyCreatedDialog
          open
          rawKey={justCreated.raw_key}
          onDismiss={() => dispatch(clearJustCreated())}
        />
      )}

      {confirmDialog}
    </Box>
  );
}
