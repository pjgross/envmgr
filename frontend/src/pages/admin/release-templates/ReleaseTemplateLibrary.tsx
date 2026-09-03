/**
 * ReleaseTemplateLibrary — admin DataGrid of release templates.
 * Provides "New Template", per-row "Edit" and "Create release from this".
 */
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Tooltip,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import DeleteIcon from '@mui/icons-material/Delete';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import { AppDispatch, RootState } from '../../../store';
import {
  fetchReleaseTemplates,
  deleteReleaseTemplate,
  instantiateReleaseTemplate,
} from '../../../store/releaseTemplateSlice';
import type { ReleaseTemplateResponse } from '../../../types/releaseTemplate';
import { useSnackbar } from '../../../hooks/useSnackbar';
import { useConfirm } from '../../../hooks/useConfirm';
import { toIsoDatetime } from '../../../utils/dates';
import PageHeader from '../../../components/layout/PageHeader';

export default function ReleaseTemplateLibrary() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const { confirm, dialog: confirmDialog } = useConfirm();
  const { list: templates, loading } = useSelector((s: RootState) => s.releaseTemplate);

  const [instantiateTarget, setInstantiateTarget] = useState<ReleaseTemplateResponse | null>(null);
  const [releaseName, setReleaseName] = useState('');
  const [targetDate, setTargetDate] = useState('');
  const [instantiating, setInstantiating] = useState(false);

  useEffect(() => {
    dispatch(fetchReleaseTemplates());
  }, [dispatch]);

  const handleDelete = async (row: ReleaseTemplateResponse) => {
    if (!(await confirm({ message: `Delete template "${row.name}"?`, destructive: true }))) return;
    try {
      await dispatch(deleteReleaseTemplate(row.id)).unwrap();
      snackbar.success('Template deleted');
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete template');
    }
  };

  const handleInstantiate = async () => {
    if (!instantiateTarget || !releaseName.trim() || !targetDate) return;
    setInstantiating(true);
    try {
      const result = await dispatch(
        instantiateReleaseTemplate({
          id: instantiateTarget.id,
          data: { name: releaseName.trim(), target_date: toIsoDatetime(targetDate) ?? '' },
        })
      ).unwrap();
      snackbar.success('Release created from template');
      setInstantiateTarget(null);
      navigate(`/releases/${result.id}`);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to create release');
      setInstantiating(false);
    }
  };

  const columns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1, minWidth: 180 },
    { field: 'release_type', headerName: 'Type', width: 120 },
    { field: 'description', headerName: 'Description', flex: 1.5, minWidth: 200 },
    {
      field: 'phases',
      headerName: 'Phases',
      width: 80,
      renderCell: (params: GridRenderCellParams<ReleaseTemplateResponse>) =>
        params.row.phases?.length ?? 0,
    },
    {
      field: 'gates',
      headerName: 'Gates',
      width: 80,
      renderCell: (params: GridRenderCellParams<ReleaseTemplateResponse>) =>
        params.row.gates?.length ?? 0,
    },
    {
      field: 'actions',
      headerName: '',
      width: 130,
      sortable: false,
      filterable: false,
      renderCell: (params: GridRenderCellParams<ReleaseTemplateResponse>) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Tooltip title="Edit template">
            <IconButton
              size="small"
              onClick={() => navigate(`/admin/releases/templates/${params.row.id}`)}
            >
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Create release from this template">
            <IconButton
              size="small"
              color="primary"
              onClick={() => {
                setInstantiateTarget(params.row);
                setReleaseName('');
                setTargetDate('');
              }}
            >
              <PlayArrowIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete template">
            <IconButton
              size="small"
              color="error"
              onClick={() => handleDelete(params.row)}
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Release Template Library"
        actions={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate('/admin/releases/templates/new')}
          >
            New Template
          </Button>
        }
      />

      <DataGrid
        rows={templates}
        columns={columns}
        loading={loading}
        autoHeight
        pageSizeOptions={[25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        disableRowSelectionOnClick
        sx={{ bgcolor: 'background.paper' }}
      />

      {confirmDialog}
      {/* Instantiate dialog */}
      <Dialog
        open={Boolean(instantiateTarget)}
        onClose={() => setInstantiateTarget(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Create Release from "{instantiateTarget?.name}"</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="Release Name"
              fullWidth
              required
              value={releaseName}
              onChange={(e) => setReleaseName(e.target.value)}
            />
            <TextField
              label="Target Date"
              type="date"
              fullWidth
              required
              InputLabelProps={{ shrink: true }}
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setInstantiateTarget(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={handleInstantiate}
            disabled={instantiating || !releaseName.trim() || !targetDate}
          >
            {instantiating ? 'Creating…' : 'Create Release'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
