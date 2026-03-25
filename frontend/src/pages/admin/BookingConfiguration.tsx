import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box, Button, Typography, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  createBookingType,
  copyLifecycleTemplate,
} from '../../store/bookingLifecycleSlice';

export default function BookingConfiguration() {
  const dispatch = useDispatch<AppDispatch>();
  const { templates, bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);

  const [createTypeOpen, setCreateTypeOpen] = useState(false);
  const [newTypeName, setNewTypeName] = useState('');
  const [newTypeTemplateId, setNewTypeTemplateId] = useState<number | ''>('');

  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
  }, [dispatch]);

  const handleCreateType = async () => {
    if (!newTypeName || !newTypeTemplateId) return;
    await dispatch(createBookingType({
      name: newTypeName,
      lifecycle_template_id: Number(newTypeTemplateId),
      is_active: true,
      description: null,
      color: null,
    }));
    setCreateTypeOpen(false);
    setNewTypeName('');
    setNewTypeTemplateId('');
  };

  const typeColumns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'lifecycle_template_id',
      headerName: 'Lifecycle Template',
      flex: 1,
      renderCell: (params) => {
        const tmpl = templates.find((t) => t.id === params.value);
        return tmpl?.name ?? String(params.value);
      },
    },
    {
      field: 'is_active',
      headerName: 'Status',
      width: 110,
      renderCell: (params) => (
        <Chip
          label={params.value ? 'Active' : 'Inactive'}
          color={params.value ? 'success' : 'default'}
          size="small"
        />
      ),
    },
  ];

  const templateColumns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'definition',
      headerName: 'States',
      width: 90,
      renderCell: (params) => (params.value as { states?: unknown[] })?.states?.length ?? 0,
    },
    {
      field: 'id',
      headerName: 'Used by',
      width: 110,
      renderCell: (params) =>
        `${bookingTypes.filter((bt) => bt.lifecycle_template_id === params.value).length} type(s)`,
    },
    {
      field: 'actions',
      headerName: '',
      width: 120,
      sortable: false,
      renderCell: (params) => (
        <Button
          size="small"
          onClick={() =>
            dispatch(copyLifecycleTemplate({ id: params.row.id as number, name: `${params.row.name as string} (copy)` }))
          }
        >
          Copy
        </Button>
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>Booking Configuration</Typography>

      <Box sx={{ mb: 4 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6">Booking Types</Typography>
          <Button variant="contained" size="small" onClick={() => setCreateTypeOpen(true)}>
            + New Type
          </Button>
        </Box>
        <DataGrid
          rows={bookingTypes}
          columns={typeColumns}
          loading={loading}
          autoHeight
          disableRowSelectionOnClick
          pageSizeOptions={[10, 25]}
        />
      </Box>

      <Dialog open={createTypeOpen} onClose={() => setCreateTypeOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Booking Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          <TextField
            label="Name"
            required
            value={newTypeName}
            onChange={(e) => setNewTypeName(e.target.value)}
          />
          <TextField
            select
            label="Lifecycle Template"
            required
            value={newTypeTemplateId}
            onChange={(e) => setNewTypeTemplateId(Number(e.target.value))}
          >
            {templates.map((t) => (
              <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>
            ))}
          </TextField>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateTypeOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleCreateType}
            disabled={!newTypeName || !newTypeTemplateId}
          >
            Create
          </Button>
        </DialogActions>
      </Dialog>

      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="h6">Lifecycle Templates</Typography>
        </Box>
        <DataGrid
          rows={templates}
          columns={templateColumns}
          loading={loading}
          autoHeight
          disableRowSelectionOnClick
          pageSizeOptions={[10, 25]}
        />
      </Box>
    </Box>
  );
}
