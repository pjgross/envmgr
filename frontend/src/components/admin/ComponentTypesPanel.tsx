import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box,
  Button,
  Typography,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Alert,
} from '@mui/material';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchComponentTypes,
  createComponentType,
  updateComponentType,
  deleteComponentType,
} from '../../store/componentTypeSlice';
import type { ComponentTypeDefinitionResponse } from '../../types/componentType';
import ComponentTypeDialog from './ComponentTypeDialog';

const CATEGORY_LABELS: Record<string, string> = {
  web_service: 'Web Service',
  api_gateway: 'API Gateway',
  database: 'Database',
  cache: 'Cache',
  message_queue: 'Message Queue',
  worker: 'Worker',
  frontend: 'Frontend',
  other: 'Other',
};

export default function ComponentTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { definitions, loading } = useSelector((s: RootState) => s.componentType);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ComponentTypeDefinitionResponse | null>(null);

  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchComponentTypes());
  }, [dispatch]);

  const handleCreate = () => {
    setEditTarget(null);
    setDialogOpen(true);
  };

  const handleEdit = (row: ComponentTypeDefinitionResponse) => {
    setEditTarget(row);
    setDialogOpen(true);
  };

  const handleSave = async (data: Parameters<typeof createComponentType>[0]) => {
    if (editTarget) {
      const result = await dispatch(updateComponentType({ id: editTarget.id, data }));
      if (updateComponentType.rejected.match(result)) {
        // `payload`, not `error.message` — see the comment on the thunks.
        throw new Error(result.payload ?? 'Failed to update');
      }
    } else {
      const result = await dispatch(createComponentType(data));
      if (createComponentType.rejected.match(result)) {
        throw new Error(result.payload ?? 'Failed to create');
      }
    }
  };

  const handleDeleteOpen = (id: number) => {
    setDeleteId(id);
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (deleteId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteComponentType(deleteId));
    if (deleteComponentType.rejected.match(result)) {
      setDeleteError(result.payload ?? 'Failed to delete');
      return;
    }
    setDeleteOpen(false);
    setDeleteId(null);
  };

  const columns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'category',
      headerName: 'Category',
      width: 140,
      renderCell: (params) =>
        params.value ? (
          <Chip label={CATEGORY_LABELS[params.value as string] ?? params.value} size="small" />
        ) : (
          <Typography variant="body2" color="text.secondary">
            --
          </Typography>
        ),
    },
    {
      field: 'field_definitions',
      headerName: 'Fields',
      width: 80,
      renderCell: (params) => (params.value as unknown[] | null)?.length ?? 0,
    },
    {
      field: 'description',
      headerName: 'Description',
      flex: 1,
      renderCell: (params) =>
        params.value ? (
          <Typography variant="body2" noWrap>
            {params.value as string}
          </Typography>
        ) : (
          <Typography variant="body2" color="text.secondary">
            --
          </Typography>
        ),
    },
    {
      field: 'actions',
      headerName: '',
      width: 140,
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button
            size="small"
            onClick={() => handleEdit(params.row as ComponentTypeDefinitionResponse)}
          >
            Edit
          </Button>
          <Button
            size="small"
            color="error"
            onClick={() => handleDeleteOpen(params.row.id as number)}
          >
            Delete
          </Button>
        </Box>
      ),
    },
  ];

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Component Types</Typography>
        <Button variant="contained" size="small" onClick={handleCreate}>
          + New Type
        </Button>
      </Box>

      <DataTable
        storageKey="admin-component-types"
        emptyMessage="No component types configured yet."
        rows={definitions}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <ComponentTypeDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSave={handleSave}
        editTarget={editTarget}
      />

      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Component Type</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this component type? Subsystems using it will keep their
            data but lose the type association.
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
