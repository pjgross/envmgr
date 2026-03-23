import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  Paper,
  Skeleton,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
  Alert,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import SearchIcon from '@mui/icons-material/Search';
import LinkIcon from '@mui/icons-material/Link';

import type { AppDispatch, RootState } from '../../store';
import {
  fetchSystems,
  createSystem,
  updateSystem,
  deleteSystem,
} from '../../store/systemSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { SystemResponse, SystemCreate, SystemUpdate } from '../../types/system';
import CustomFieldsSection from '../../components/CustomFieldsSection';

interface SystemFormValues {
  name: string;
  description: string;
  github_repository_url: string;
}

const emptyForm: SystemFormValues = { name: '', description: '', github_repository_url: '' };

export default function SystemCatalog() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { systems, loading, error } = useSelector((state: RootState) => state.system);

  const customFieldDefs = useSelector((state: RootState) => state.customField.definitions['system'] ?? []);

  const [search, setSearch] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SystemResponse | null>(null);
  const [form, setForm] = useState<SystemFormValues>(emptyForm);
  const [formError, setFormError] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<SystemResponse | null>(null);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  useEffect(() => {
    dispatch(fetchSystems());
    dispatch(fetchDefinitions('system'));
  }, [dispatch]);

  const filtered = systems.filter((s) =>
    s.name.toLowerCase().includes(search.toLowerCase())
  );

  const openCreate = () => {
    setEditTarget(null);
    setForm(emptyForm);
    setFormError('');
    setCustomFieldValues({});
    setDialogOpen(true);
  };

  const openEdit = (system: SystemResponse) => {
    setEditTarget(system);
    setForm({
      name: system.name,
      description: system.description ?? '',
      github_repository_url: system.github_repository_url ?? '',
    });
    setFormError('');
    setCustomFieldValues(system.custom_fields ?? {});
    setDialogOpen(true);
  };

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
    } finally {
      setDeleteTarget(null);
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

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>GitHub</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {loading && systems.length === 0
              ? Array.from({ length: 4 }).map((_, i) => (
                  <TableRow key={i}>
                    {Array.from({ length: 4 }).map((__, j) => (
                      <TableCell key={j}>
                        <Skeleton />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : filtered.map((system) => (
                  <TableRow
                    key={system.id}
                    hover
                    sx={{ cursor: 'pointer' }}
                    onClick={() => navigate(`/systems/${system.id}`)}
                  >
                    <TableCell>
                      <Typography variant="body2" fontWeight="medium">
                        {system.name}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" color="text.secondary">
                        {system.description ?? '—'}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      {system.github_repository_url ? (
                        <Chip
                          icon={<LinkIcon />}
                          label="GitHub"
                          size="small"
                          component="a"
                          href={system.github_repository_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          clickable
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        '—'
                      )}
                    </TableCell>
                    <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                      <Tooltip title="Edit">
                        <IconButton size="small" onClick={() => openEdit(system)}>
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Delete">
                        <IconButton
                          size="small"
                          color="error"
                          onClick={() => setDeleteTarget(system)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
            {!loading && filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} align="center">
                  <Typography color="text.secondary" py={3}>
                    {search ? 'No systems match your search.' : 'No systems yet. Create one!'}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); setCustomFieldValues({}); }} maxWidth="sm" fullWidth>
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
          <Button onClick={() => { setDialogOpen(false); setCustomFieldValues({}); }}>Cancel</Button>
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
