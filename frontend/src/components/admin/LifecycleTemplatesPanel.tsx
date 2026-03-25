import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, FormControlLabel,
  IconButton, MenuItem, TextField, Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  copyLifecycleTemplate,
  createLifecycleTemplate,
} from '../../store/bookingLifecycleSlice';

const ROLES = ['Admin', 'Release Manager', 'Test Manager', 'Developer', 'Viewer'];

interface StateRow {
  key: string;
  label: string;
  is_initial: boolean;
  is_terminal: boolean;
}

interface TransitionRow {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

const emptyState = (): StateRow => ({ key: '', label: '', is_initial: false, is_terminal: false });
const emptyTransition = (): TransitionRow => ({ from_state: '', to_state: '', label: '', allowed_roles: [] });

export default function LifecycleTemplatesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { templates, bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);

  // Dialog state
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [states, setStates] = useState<StateRow[]>([]);
  const [transitions, setTransitions] = useState<TransitionRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    dispatch(fetchLifecycleTemplates());
    dispatch(fetchBookingTypes());
  }, [dispatch]);

  // --- Validation ---

  function validate(): string | null {
    if (!name.trim()) return 'Name is required';
    if (states.length === 0) return 'At least one state is required';
    const initialCount = states.filter((s) => s.is_initial).length;
    if (initialCount !== 1) return 'Exactly one state must be marked as initial';
    const keys = states.map((s) => s.key.trim());
    if (keys.some((k) => !k)) return 'All state keys must be non-empty';
    if (new Set(keys).size !== keys.length) return 'State keys must be unique';
    for (const t of transitions) {
      if (!t.label.trim()) return 'All transitions must have a label';
      if (!t.from_state || !t.to_state) return 'All transitions must have from and to states';
      if (!keys.includes(t.from_state) || !keys.includes(t.to_state))
        return 'Transitions must reference valid state keys';
      if (t.allowed_roles.length === 0) return 'Each transition must have at least one allowed role';
    }
    return null;
  }

  // --- Handlers ---

  const handleOpen = () => {
    setName('');
    setDescription('');
    setStates([]);
    setTransitions([]);
    setError(null);
    setOpen(true);
  };

  const handleClose = () => setOpen(false);

  const handleCreate = async () => {
    const err = validate();
    if (err) { setError(err); return; }
    setError(null);
    setSaving(true);
    const result = await dispatch(createLifecycleTemplate({
      name: name.trim(),
      description: description.trim() || null,
      is_default: false,
      definition: {
        states: states.map((s) => ({
          key: s.key.trim(),
          label: s.label.trim(),
          is_initial: s.is_initial,
          is_terminal: s.is_terminal,
        })),
        transitions: transitions.map((t) => ({
          from_state: t.from_state,
          to_state: t.to_state,
          label: t.label.trim(),
          allowed_roles: t.allowed_roles,
        })),
        field_permissions: {},
      },
    }));
    setSaving(false);
    if (createLifecycleTemplate.rejected.match(result)) {
      setError(result.error.message ?? 'Failed to create template');
      return;
    }
    handleClose();
  };

  // State row helpers
  const updateState = (i: number, patch: Partial<StateRow>) =>
    setStates((prev) => prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const removeState = (i: number) => setStates((prev) => prev.filter((_, idx) => idx !== i));

  // Transition row helpers
  const updateTransition = (i: number, patch: Partial<TransitionRow>) =>
    setTransitions((prev) => prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  const removeTransition = (i: number) => setTransitions((prev) => prev.filter((_, idx) => idx !== i));
  const toggleRole = (i: number, role: string) => {
    const t = transitions[i];
    const roles = t.allowed_roles.includes(role)
      ? t.allowed_roles.filter((r) => r !== role)
      : [...t.allowed_roles, role];
    updateTransition(i, { allowed_roles: roles });
  };

  const stateKeys = states.map((s) => s.key.trim()).filter(Boolean);

  // --- DataGrid columns ---

  const columns: GridColDef[] = [
    { field: 'name', headerName: 'Name', flex: 1 },
    {
      field: 'definition',
      headerName: 'States',
      width: 80,
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
      width: 100,
      sortable: false,
      renderCell: (params) => (
        <Button
          size="small"
          onClick={() =>
            dispatch(copyLifecycleTemplate({
              id: params.row.id as number,
              name: `${params.row.name as string} (copy)`,
            }))
          }
        >
          Copy
        </Button>
      ),
    },
  ];

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Lifecycle Templates</Typography>
        <Button variant="contained" size="small" onClick={handleOpen}>
          + New Template
        </Button>
      </Box>

      <DataGrid
        rows={templates}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      {/* New Template Dialog */}
      <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
        <DialogTitle>New Lifecycle Template</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {error && <Alert severity="error">{error}</Alert>}

          {/* Name & Description */}
          <TextField
            label="Name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            fullWidth
          />
          <TextField
            label="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            multiline
            rows={2}
            fullWidth
          />

          <Divider />

          {/* States */}
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle2">States</Typography>
              <Button size="small" startIcon={<AddIcon />} onClick={() => setStates((p) => [...p, emptyState()])}>
                Add State
              </Button>
            </Box>

            {states.length === 0 && (
              <Typography variant="body2" color="text.secondary">No states yet. Add at least one.</Typography>
            )}

            {states.map((s, i) => (
              <Box key={i} sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1, flexWrap: 'wrap' }}>
                <TextField
                  label="Key"
                  size="small"
                  value={s.key}
                  onChange={(e) => updateState(i, { key: e.target.value })}
                  sx={{ width: 140 }}
                  placeholder="e.g. draft"
                />
                <TextField
                  label="Label"
                  size="small"
                  value={s.label}
                  onChange={(e) => updateState(i, { label: e.target.value })}
                  sx={{ width: 160 }}
                  placeholder="e.g. Draft"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={s.is_initial}
                      onChange={(e) => updateState(i, { is_initial: e.target.checked })}
                    />
                  }
                  label="Initial"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      size="small"
                      checked={s.is_terminal}
                      onChange={(e) => updateState(i, { is_terminal: e.target.checked })}
                    />
                  }
                  label="Terminal"
                />
                <IconButton size="small" onClick={() => removeState(i)}>
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
          </Box>

          <Divider />

          {/* Transitions */}
          <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle2">Transitions</Typography>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() => setTransitions((p) => [...p, emptyTransition()])}
                disabled={stateKeys.length < 2}
              >
                Add Transition
              </Button>
            </Box>

            {stateKeys.length < 2 && (
              <Typography variant="body2" color="text.secondary">
                Add at least two states with keys before defining transitions.
              </Typography>
            )}

            {transitions.map((t, i) => (
              <Box key={i} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 1 }}>
                  <TextField
                    select
                    label="From"
                    size="small"
                    value={t.from_state}
                    onChange={(e) => updateTransition(i, { from_state: e.target.value })}
                    sx={{ width: 150 }}
                  >
                    {stateKeys.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                  </TextField>
                  <TextField
                    select
                    label="To"
                    size="small"
                    value={t.to_state}
                    onChange={(e) => updateTransition(i, { to_state: e.target.value })}
                    sx={{ width: 150 }}
                  >
                    {stateKeys.map((k) => <MenuItem key={k} value={k}>{k}</MenuItem>)}
                  </TextField>
                  <TextField
                    label="Label"
                    size="small"
                    value={t.label}
                    onChange={(e) => updateTransition(i, { label: e.target.value })}
                    sx={{ width: 180 }}
                    placeholder="e.g. Submit"
                  />
                  <IconButton size="small" onClick={() => removeTransition(i)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {ROLES.map((role) => (
                    <Chip
                      key={role}
                      label={role}
                      size="small"
                      clickable
                      color={t.allowed_roles.includes(role) ? 'primary' : 'default'}
                      variant={t.allowed_roles.includes(role) ? 'filled' : 'outlined'}
                      onClick={() => toggleRole(i, role)}
                    />
                  ))}
                </Box>
              </Box>
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button variant="contained" onClick={handleCreate} disabled={saving}>
            {saving ? 'Creating...' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
