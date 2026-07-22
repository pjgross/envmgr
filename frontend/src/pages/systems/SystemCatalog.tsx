import { useCallback, useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  DataGrid,
  GridColDef,
  GridColumnVisibilityModel,
  GridValueGetterParams,
} from '@mui/x-data-grid';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';
import LinkIcon from '@mui/icons-material/Link';

import type { AppDispatch, RootState } from '../../store';
import { fetchSystems, createSystem, updateSystem, deleteSystem } from '../../store/systemSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { SystemResponse, SystemCreate, SystemUpdate } from '../../types/system';
import CustomFieldsSection from '../../components/CustomFieldsSection';
import { useSnackbar } from '../../hooks/useSnackbar';

interface SystemFormValues {
  name: string;
  description: string;
  github_repository_url: string;
}

const emptyForm: SystemFormValues = { name: '', description: '', github_repository_url: '' };

function loadColumnModel(userId: number | string | undefined): GridColumnVisibilityModel {
  const key = `systems-list-columns-${userId ?? 'guest'}`;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return {};
    return JSON.parse(raw) ?? {};
  } catch {
    return {};
  }
}

function saveColumnModel(userId: number | string | undefined, model: GridColumnVisibilityModel) {
  const key = `systems-list-columns-${userId ?? 'guest'}`;
  try {
    localStorage.setItem(key, JSON.stringify(model));
  } catch {
    // quota exceeded or storage unavailable — silently skip persistence
  }
}

export default function SystemCatalog() {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const navigate = useNavigate();
  const { systems, loading, error } = useSelector((state: RootState) => state.system);

  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions['system'] ?? []
  );

  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SystemResponse | null>(null);
  const [form, setForm] = useState<SystemFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SystemResponse | null>(null);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  const user = useSelector((state: RootState) => state.auth.user);
  const [columnVisibilityModel, setColumnVisibilityModel] = useState<GridColumnVisibilityModel>(
    () => loadColumnModel(user?.id)
  );

  useEffect(() => {
    dispatch(fetchSystems());
    dispatch(fetchDefinitions('system'));
  }, [dispatch]);

  const filtered = useMemo(
    () => systems.filter((s) => s.name.toLowerCase().includes(search.toLowerCase())),
    [systems, search]
  );

  const openCreate = useCallback(() => {
    setEditTarget(null);
    setForm(emptyForm);
    setFormError('');
    setCustomFieldValues({});
    setDialogOpen(true);
  }, []);

  const openEdit = useCallback((system: SystemResponse) => {
    setEditTarget(system);
    setForm({
      name: system.name,
      description: system.description ?? '',
      github_repository_url: system.github_repository_url ?? '',
    });
    setFormError('');
    setCustomFieldValues(system.custom_fields ?? {});
    setDialogOpen(true);
  }, []);

  const coreColumns = useMemo<GridColDef<SystemResponse>[]>(
    () => [
      {
        field: 'name',
        headerName: 'Name',
        flex: 1.5,
        hideable: false,
        renderCell: (params) => (
          <Typography variant="body2" fontWeight="medium">
            {params.row.name}
          </Typography>
        ),
      },
      {
        field: 'description',
        headerName: 'Description',
        flex: 2,
        hideable: false,
        valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
          params.row.description ?? '—',
      },
      {
        field: 'github_repository_url',
        headerName: 'GitHub',
        flex: 1,
        hideable: false,
        renderCell: (params) =>
          params.row.github_repository_url ? (
            <Chip
              icon={<LinkIcon />}
              label="GitHub"
              size="small"
              component="a"
              href={params.row.github_repository_url}
              target="_blank"
              rel="noopener noreferrer"
              clickable
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <Typography variant="body2" color="text.secondary">
              —
            </Typography>
          ),
      },
    ],
    []
  );

  const actionsColumn = useMemo<GridColDef<SystemResponse>>(
    () => ({
      field: 'actions',
      headerName: '',
      width: 100,
      sortable: false,
      hideable: false,
      disableColumnMenu: true,
      renderCell: (params) => (
        <Box onClick={(e) => e.stopPropagation()}>
          <Tooltip title="Edit">
            <IconButton size="small" onClick={() => openEdit(params.row)}>
              <EditIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <Tooltip title="Delete">
            <IconButton size="small" color="error" onClick={() => setDeleteTarget(params.row)}>
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Box>
      ),
    }),
    [openEdit, setDeleteTarget]
  );

  const customFieldColumns = useMemo<GridColDef<SystemResponse>[]>(
    () =>
      customFieldDefs.map(
        (def) =>
          ({
            field: def.field_key,
            headerName: def.label,
            flex: 1,
            valueGetter: (params: GridValueGetterParams<SystemResponse>) =>
              params.row.custom_fields?.[def.field_key] ?? '—',
          }) as GridColDef<SystemResponse>
      ),
    [customFieldDefs]
  );

  const columns = useMemo(
    () => [...coreColumns, ...customFieldColumns, actionsColumn],
    [coreColumns, customFieldColumns, actionsColumn]
  );

  const handleColumnVisibilityChange = useCallback(
    (model: GridColumnVisibilityModel) => {
      setColumnVisibilityModel(model);
      saveColumnModel(user?.id, model);
    },
    [user?.id]
  );

  const handleSave = async () => {
    if (!form.name.trim()) {
      setFormError('Name is required');
      return;
    }
    try {
      if (editTarget) {
        const data: SystemUpdate = {
          name: form.name,
          description: form.description || undefined,
          github_repository_url: form.github_repository_url || undefined,
          custom_fields: customFieldValues,
        };
        await dispatch(updateSystem({ id: editTarget.id, data })).unwrap();
      } else {
        const data: SystemCreate = {
          name: form.name,
          description: form.description || undefined,
          github_repository_url: form.github_repository_url || undefined,
          custom_fields: customFieldValues,
        };
        await dispatch(createSystem(data)).unwrap();
      }
      setDialogOpen(false);
      setCustomFieldValues({});
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setFormError(message || 'Failed to save system');
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    try {
      await dispatch(deleteSystem(deleteTarget.id)).unwrap();
      snackbar.success('System deleted');
      setDeleteTarget(null);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to delete system');
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3, gap: 2 }}>
        <Typography variant="h5" fontWeight="bold" sx={{ flexGrow: 1 }}>
          System Catalog
        </Typography>
        <TextField
          size="small"
          placeholder="Search systems…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Button variant="contained" startIcon={<AddIcon />} onClick={openCreate}>
          New System
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <DataGrid
        rows={filtered}
        columns={columns}
        loading={loading && systems.length === 0}
        onRowClick={(params) => navigate(`/systems/${params.row.id}`)}
        columnVisibilityModel={columnVisibilityModel}
        onColumnVisibilityModelChange={handleColumnVisibilityChange}
        pageSizeOptions={[25, 50, 100]}
        initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
        sx={{ border: 1, borderColor: 'divider' }}
        disableRowSelectionOnClick
      />

      {/* Create / Edit Dialog */}
      <Dialog
        open={dialogOpen}
        onClose={() => {
          setDialogOpen(false);
          setCustomFieldValues({});
        }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{editTarget ? 'Edit System' : 'New System'}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {formError && <Alert severity="error">{formError}</Alert>}
          <TextField
            label="Name"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            fullWidth
          />
          <TextField
            label="Description"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            fullWidth
            multiline
            rows={2}
          />
          <TextField
            label="GitHub Repository URL"
            value={form.github_repository_url}
            onChange={(e) => setForm({ ...form, github_repository_url: e.target.value })}
            fullWidth
            placeholder="https://github.com/org/repo"
          />
          <CustomFieldsSection
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={setCustomFieldValues}
          />
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setDialogOpen(false);
              setCustomFieldValues({});
            }}
          >
            Cancel
          </Button>
          <Button onClick={handleSave} variant="contained" disabled={loading}>
            {editTarget ? 'Save' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>Delete System</DialogTitle>
        <DialogContent>
          <Typography>
            Are you sure you want to delete <strong>{deleteTarget?.name}</strong>? This will also
            delete all its subsystems.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
          <Button onClick={handleDelete} color="error" variant="contained">
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
