import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  FormHelperText,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Radio,
  RadioGroup,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  copyLifecycleTemplate,
  createLifecycleTemplate,
  updateLifecycleTemplate,
  deleteLifecycleTemplate,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import type { BookingLifecycleTemplate } from '../../types/bookingLifecycle';
import type { EntityType } from '../../types/customField';

const ALL_ROLES = ['Admin', 'Release Manager', 'Test Manager', 'Developer', 'Viewer'];

interface StandardField {
  key: string;
  label: string;
  mandatory: boolean;
}

const STANDARD_FIELDS_BY_ENTITY: Partial<Record<EntityType, StandardField[]>> = {
  booking: [
    { key: 'project_name', label: 'Purpose', mandatory: true },
    { key: 'start_date', label: 'Start Date', mandatory: true },
    { key: 'end_date', label: 'End Date', mandatory: true },
    { key: 'booking_type', label: 'Booking Type', mandatory: true },
    { key: 'notes', label: 'Notes', mandatory: false },
    { key: 'exclusive_use', label: 'Exclusive Use', mandatory: false },
    { key: 'context_tag', label: 'Context Tag', mandatory: false },
  ],
  change_request: [
    { key: 'title', label: 'Title', mandatory: true },
    { key: 'description', label: 'Description', mandatory: false },
    { key: 'change_type', label: 'Change Type', mandatory: true },
    { key: 'scheduled_start', label: 'Scheduled Start', mandatory: true },
    { key: 'scheduled_end', label: 'Scheduled End', mandatory: true },
    { key: 'has_outage', label: 'Has Outage', mandatory: false },
    { key: 'outage_start', label: 'Outage Start', mandatory: false },
    { key: 'outage_end', label: 'Outage End', mandatory: false },
  ],
  release: [
    { key: 'name', label: 'Name', mandatory: true },
    { key: 'description', label: 'Description', mandatory: false },
    { key: 'release_type', label: 'Release Type', mandatory: true },
    { key: 'target_date', label: 'Target Date', mandatory: false },
    { key: 'actual_date', label: 'Actual Date', mandatory: false },
  ],
  incident: [
    { key: 'title', label: 'Title', mandatory: true },
    { key: 'severity', label: 'Severity', mandatory: true },
    { key: 'detected_at', label: 'Detected At', mandatory: true },
    { key: 'description', label: 'Description', mandatory: false },
    { key: 'resolved_at', label: 'Resolved At', mandatory: false },
  ],
};

interface StateRow {
  key: string;
  label: string;
  is_initial: boolean;
  is_terminal: boolean;
  is_admission_lockdown: boolean;
  is_failed?: boolean;
}

interface TransitionRow {
  from_state: string;
  to_state: string;
  label: string;
  allowed_roles: string[];
}

interface FieldPermState {
  standard_fields: Record<string, { editable_by: string[] }>;
  custom_fields: Record<string, { editable_by: string[] }>;
}

const emptyState = (): StateRow => ({
  key: '',
  label: '',
  is_initial: false,
  is_terminal: false,
  is_admission_lockdown: false,
  is_failed: false,
});
const emptyTransition = (): TransitionRow => ({
  from_state: '',
  to_state: '',
  label: '',
  allowed_roles: [],
});

interface LifecycleTemplatesPanelProps {
  /** Which entity's templates this panel manages. Defaults to 'booking' for
   * back-compat with existing call sites. */
  entityType?: EntityType;
}

export default function LifecycleTemplatesPanel({
  entityType = 'booking',
}: LifecycleTemplatesPanelProps = {}) {
  const dispatch = useDispatch<AppDispatch>();
  const { bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);
  const templates = useSelector(selectTemplatesForEntity(entityType));
  const customFieldDefs = useSelector(
    (state: RootState) => state.customField.definitions[entityType] ?? []
  );
  const STANDARD_FIELDS: StandardField[] = STANDARD_FIELDS_BY_ENTITY[entityType] ?? [];

  // Dialog state
  const [open, setOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [appliesToKind, setAppliesToKind] = useState<string | null>(null);
  const [states, setStates] = useState<StateRow[]>([]);
  const [transitions, setTransitions] = useState<TransitionRow[]>([]);
  const [fieldPerms, setFieldPerms] = useState<Record<string, FieldPermState>>({});
  // Enterprise-only: action permissions matrix { [stateKey]: { [action]: [...roles] } }
  const [actionPermissions, setActionPermissions] = useState<
    Record<string, Record<string, string[]>>
  >({});
  const [editTemplateId, setEditTemplateId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldPermErrors, setFieldPermErrors] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  // Delete confirm dialog
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleteTemplateId, setDeleteTemplateId] = useState<number | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchLifecycleTemplates(entityType));
    // Booking types are only meaningful for bookings; skip the fetch for
    // other entities to keep the network quiet and the "in-use" delete
    // guard applies only where booking_type rows reference the template.
    if (entityType === 'booking') {
      dispatch(fetchBookingTypes());
    }
    dispatch(fetchDefinitions(entityType));
  }, [dispatch, entityType]);

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
      if (!(t.label ?? '').trim()) return 'All transitions must have a label';
      if (!t.from_state || !t.to_state) return 'All transitions must have from and to states';
      if (!keys.includes(t.from_state) || !keys.includes(t.to_state))
        return 'Transitions must reference valid state keys';
      if (t.allowed_roles.length === 0)
        return 'Each transition must have at least one allowed role';
    }
    return null;
  }

  function validateFieldPerms(): string[] {
    const errors: string[] = [];
    const initialState = states.find((s) => s.is_initial);
    if (!initialState) return errors;
    const initKey = initialState.key.trim();
    const initPerms = fieldPerms[initKey];
    for (const field of STANDARD_FIELDS.filter((f) => f.mandatory)) {
      const editableBy = initPerms?.standard_fields?.[field.key]?.editable_by ?? [];
      if (editableBy.length === 0) {
        errors.push(
          `Field '${field.label}' must have at least one editable role in the initial state`
        );
      }
    }
    return errors;
  }

  // --- Handlers ---

  const handleOpen = () => {
    setName('');
    setDescription('');
    setAppliesToKind(null);
    setStates([]);
    setTransitions([]);
    setFieldPerms({});
    setActionPermissions({});
    setEditTemplateId(null);
    setError(null);
    setFieldPermErrors([]);
    setOpen(true);
  };

  const handleClose = () => {
    setEditTemplateId(null);
    setOpen(false);
  };

  const handleEditOpen = (template: BookingLifecycleTemplate) => {
    setEditTemplateId(template.id);
    setName(template.name);
    setDescription(template.description ?? '');
    setAppliesToKind(template.applies_to_kind ?? null);
    setStates(
      template.definition.states.map((s) => ({
        key: s.key,
        label: s.label,
        is_initial: s.is_initial,
        is_terminal: s.is_terminal,
        is_admission_lockdown: s.is_admission_lockdown ?? false,
        is_failed: s.is_failed ?? false,
      }))
    );
    setTransitions(
      template.definition.transitions.map((t) => ({
        from_state: t.from_state,
        to_state: t.to_state,
        // Older seeded templates may lack `label`; coerce to empty string so
        // the UI renders and the validator can surface a readable error
        // ("All transitions must have a label") instead of TypeError on
        // undefined.trim().
        label: t.label ?? '',
        allowed_roles: t.allowed_roles,
      }))
    );
    const fp: Record<string, FieldPermState> = {};
    for (const [stateKey, perm] of Object.entries(template.definition.field_permissions ?? {})) {
      const permAny = perm as unknown as Record<string, unknown>;
      if (permAny.editable_fields !== undefined) {
        // Old shape: convert to new shape; filter out legacy invalid role strings
        const validRolesSet = new Set(ALL_ROLES);
        const oldEditableFields = (permAny.editable_fields as string[]) ?? [];
        const oldEditableBy = ((permAny.editable_by as string[]) ?? []).filter((r) =>
          validRolesSet.has(r)
        );
        fp[stateKey] = {
          standard_fields: Object.fromEntries(
            STANDARD_FIELDS.map((f) => [
              f.key,
              { editable_by: oldEditableFields.includes(f.key) ? oldEditableBy : [] },
            ])
          ),
          custom_fields: (permAny.custom_fields as Record<string, { editable_by: string[] }>) ?? {},
        };
      } else {
        // New shape
        const stdFields =
          (permAny.standard_fields as Record<string, { editable_by: string[] }> | undefined) ?? {};
        fp[stateKey] = {
          standard_fields: Object.fromEntries(
            STANDARD_FIELDS.map((f) => [
              f.key,
              { editable_by: stdFields[f.key]?.editable_by ?? [] },
            ])
          ),
          custom_fields: (permAny.custom_fields as Record<string, { editable_by: string[] }>) ?? {},
        };
      }
    }
    setFieldPerms(fp);
    setActionPermissions(
      (template.definition.action_permissions as Record<string, Record<string, string[]>>) ?? {}
    );
    setError(null);
    setFieldPermErrors([]);
    setOpen(true);
  };

  const handleSave = async () => {
    const err = validate();
    if (err) {
      setError(err);
      return;
    }

    const fpErrors = validateFieldPerms();
    if (fpErrors.length > 0) {
      setFieldPermErrors(fpErrors);
      return;
    }
    setFieldPermErrors([]);
    setError(null);
    setSaving(true);
    const isEnterprise = appliesToKind === 'enterprise';
    const definition = {
      states: states.map((s) => ({
        key: s.key.trim(),
        label: s.label.trim(),
        is_initial: s.is_initial,
        is_terminal: s.is_terminal,
        ...(isEnterprise ? { is_admission_lockdown: s.is_admission_lockdown } : {}),
        ...(s.is_terminal && s.is_failed ? { is_failed: true } : {}),
      })),
      transitions: transitions.map((t) => ({
        from_state: t.from_state,
        to_state: t.to_state,
        label: t.label.trim(),
        allowed_roles: t.allowed_roles,
      })),
      field_permissions: Object.fromEntries(
        stateKeys.map((key) => {
          const perm = fieldPerms[key] ?? { standard_fields: {}, custom_fields: {} };
          return [
            key,
            { standard_fields: perm.standard_fields, custom_fields: perm.custom_fields },
          ];
        })
      ),
      ...(isEnterprise ? { action_permissions: actionPermissions } : {}),
    };

    let result;
    if (editTemplateId !== null) {
      result = await dispatch(
        updateLifecycleTemplate({
          id: editTemplateId,
          data: {
            name: name.trim(),
            description: description.trim() || null,
            applies_to_kind: appliesToKind,
            definition,
          },
        })
      );
    } else {
      result = await dispatch(
        createLifecycleTemplate({
          entityType,
          data: {
            name: name.trim(),
            description: description.trim() || null,
            is_default: false,
            applies_to_kind: appliesToKind,
            definition,
          },
        })
      );
    }
    setSaving(false);
    if ('error' in result) {
      // `payload`, not `error.message` — see the comment on the thunks. The
      // cast is because `result` here is one of two thunk results (create or
      // update); both reject with a string payload.
      setError((result as { payload?: string }).payload ?? 'Failed to save template');
      return;
    }
    setEditTemplateId(null);
    handleClose();
  };

  // State row helpers
  const updateState = (i: number, patch: Partial<StateRow>) => {
    setStates((prev) => {
      const oldKey = prev[i].key;
      const newStates = prev.map((s, idx) => (idx === i ? { ...s, ...patch } : s));
      if (patch.key !== undefined && patch.key !== oldKey) {
        setFieldPerms((fp) => {
          const updated = { ...fp };
          if (oldKey in updated) {
            updated[patch.key!] = updated[oldKey];
            delete updated[oldKey];
          }
          return updated;
        });
        setActionPermissions((ap) => {
          const updated = { ...ap };
          if (oldKey in updated) {
            updated[patch.key!] = updated[oldKey];
            delete updated[oldKey];
          }
          return updated;
        });
      }
      return newStates;
    });
  };

  const removeState = (i: number) => {
    const key = states[i].key;
    setStates((prev) => prev.filter((_, idx) => idx !== i));
    setFieldPerms((fp) => {
      const updated = { ...fp };
      delete updated[key];
      return updated;
    });
    setActionPermissions((ap) => {
      const updated = { ...ap };
      delete updated[key];
      return updated;
    });
  };

  // Transition row helpers
  const updateTransition = (i: number, patch: Partial<TransitionRow>) =>
    setTransitions((prev) => prev.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  const removeTransition = (i: number) =>
    setTransitions((prev) => prev.filter((_, idx) => idx !== i));
  const toggleRole = (i: number, role: string) => {
    const t = transitions[i];
    const roles = t.allowed_roles.includes(role)
      ? t.allowed_roles.filter((r) => r !== role)
      : [...t.allowed_roles, role];
    updateTransition(i, { allowed_roles: roles });
  };

  /** Set the admission-lockdown state (single-select across the template). */
  const setLockdownKey = (key: string) => {
    setStates((prev) =>
      prev.map((s) => ({ ...s, is_admission_lockdown: s.key === key }))
    );
  };

  /** Toggle a role on/off for a given state+action in the admission permissions matrix. */
  const toggleActionPermission = (
    stateKey: string,
    action: string,
    role: string,
    checked: boolean
  ) => {
    setActionPermissions((prev) => {
      const statePerm = prev[stateKey] ?? {};
      const current = statePerm[action] ?? [];
      const updated = checked ? [...current, role] : current.filter((r) => r !== role);
      return {
        ...prev,
        [stateKey]: { ...statePerm, [action]: updated },
      };
    });
  };

  const handleToggleRole = (stateKey: string, fieldKey: string, role: string) => {
    setFieldPerms((prev) => {
      const state = prev[stateKey] ?? { standard_fields: {}, custom_fields: {} };
      const currentRoles = state.standard_fields[fieldKey]?.editable_by ?? [];
      const newRoles = currentRoles.includes(role)
        ? currentRoles.filter((r) => r !== role)
        : [...currentRoles, role];
      return {
        ...prev,
        [stateKey]: {
          ...state,
          standard_fields: {
            ...state.standard_fields,
            [fieldKey]: { editable_by: newRoles },
          },
        },
      };
    });
  };

  const stateKeys = states.map((s) => s.key.trim()).filter(Boolean);

  const handleDeleteOpen = (id: number) => {
    setDeleteTemplateId(id);
    setDeleteError(null);
    setDeleteOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (deleteTemplateId === null) return;
    setDeleteError(null);
    const result = await dispatch(deleteLifecycleTemplate(deleteTemplateId));
    if (deleteLifecycleTemplate.rejected.match(result)) {
      setDeleteError(result.payload ?? 'Failed to delete template');
      return;
    }
    setDeleteOpen(false);
    setDeleteTemplateId(null);
  };

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
      width: 200,
      sortable: false,
      renderCell: (params) => (
        <Box sx={{ display: 'flex', gap: 0.5 }}>
          <Button
            size="small"
            onClick={() => handleEditOpen(params.row as BookingLifecycleTemplate)}
          >
            Edit
          </Button>
          <Button
            size="small"
            onClick={() =>
              dispatch(
                copyLifecycleTemplate({
                  id: params.row.id as number,
                  name: `${params.row.name as string} (copy)`,
                })
              )
            }
          >
            Copy
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
        <Typography variant="h6">Lifecycle Templates</Typography>
        <Button variant="contained" size="small" onClick={handleOpen}>
          + New Template
        </Button>
      </Box>

      <DataTable
        storageKey="admin-lifecycle-templates"
        emptyMessage="No lifecycle templates configured yet."
        rows={templates}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      {/* Delete confirm dialog */}
      <Dialog open={deleteOpen} onClose={() => setDeleteOpen(false)} maxWidth="xs" fullWidth>
        <DialogTitle>Delete Lifecycle Template</DialogTitle>
        <DialogContent>
          {deleteError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {deleteError}
            </Alert>
          )}
          <Typography>
            Are you sure you want to delete this template? This cannot be undone.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
          <Button variant="contained" color="error" onClick={handleDeleteConfirm}>
            Delete
          </Button>
        </DialogActions>
      </Dialog>

      {/* New / Edit Template Dialog */}
      <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
        <DialogTitle>
          {editTemplateId !== null ? 'Edit Lifecycle Template' : 'New Lifecycle Template'}
        </DialogTitle>
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

          <FormControl fullWidth>
            <InputLabel id="applies-to-kind-label">Kind</InputLabel>
            <Select
              labelId="applies-to-kind-label"
              value={appliesToKind ?? ''}
              label="Kind"
              onChange={(e) => setAppliesToKind(e.target.value || null)}
            >
              <MenuItem value="">Any</MenuItem>
              <MenuItem value="project">Project</MenuItem>
              <MenuItem value="enterprise">Enterprise</MenuItem>
            </Select>
          </FormControl>

          <Divider />

          {/* States */}
          <Box>
            <Box
              sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
            >
              <Typography variant="subtitle2">States</Typography>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() => setStates((p) => [...p, emptyState()])}
              >
                Add State
              </Button>
            </Box>

            {states.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                No states yet. Add at least one.
              </Typography>
            )}

            {states.map((s, i) => (
              <Box
                key={i}
                sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1, flexWrap: 'wrap' }}
              >
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
                {s.is_terminal && (
                  <FormControlLabel
                    control={
                      <Checkbox
                        size="small"
                        checked={s.is_failed ?? false}
                        onChange={(e) => updateState(i, { is_failed: e.target.checked })}
                      />
                    }
                    label="Counts as failure"
                  />
                )}
                <IconButton
                  size="small"
                  aria-label="Remove state"
                  sx={{ p: 1 }}
                  onClick={() => removeState(i)}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Box>
            ))}
          </Box>

          <Divider />

          {/* Transitions */}
          <Box>
            <Box
              sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
            >
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
              <Box
                key={i}
                sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}
              >
                <Box
                  sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 1 }}
                >
                  <TextField
                    select
                    label="From"
                    size="small"
                    value={t.from_state}
                    onChange={(e) => updateTransition(i, { from_state: e.target.value })}
                    sx={{ width: 150 }}
                  >
                    {stateKeys.map((k) => (
                      <MenuItem key={k} value={k}>
                        {k}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    label="To"
                    size="small"
                    value={t.to_state}
                    onChange={(e) => updateTransition(i, { to_state: e.target.value })}
                    sx={{ width: 150 }}
                  >
                    {stateKeys.map((k) => (
                      <MenuItem key={k} value={k}>
                        {k}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    label="Label"
                    size="small"
                    value={t.label}
                    onChange={(e) => updateTransition(i, { label: e.target.value })}
                    sx={{ width: 180 }}
                    placeholder="e.g. Submit"
                  />
                  <IconButton
                    size="small"
                    aria-label="Remove transition"
                    sx={{ p: 1 }}
                    onClick={() => removeTransition(i)}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                  {ALL_ROLES.map((role) => (
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

          <Divider />

          {/* Field Permissions */}
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1 }}>
              Field Permissions (per state)
            </Typography>
            {fieldPermErrors.length > 0 && (
              <Box sx={{ mb: 1 }}>
                {fieldPermErrors.map((e, i) => (
                  <FormHelperText key={i} error>
                    {e}
                  </FormHelperText>
                ))}
              </Box>
            )}
            {stateKeys.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                Add states first.
              </Typography>
            ) : (
              stateKeys.map((stateKey) => {
                const perm = fieldPerms[stateKey] ?? { standard_fields: {}, custom_fields: {} };
                const cfPerms = perm.custom_fields ?? {};
                return (
                  <Box
                    key={stateKey}
                    sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1.5, mb: 1 }}
                  >
                    <Typography variant="caption" fontWeight="bold">
                      {stateKey}
                    </Typography>

                    {/* Standard Fields */}
                    <Box sx={{ mt: 1 }}>
                      <Typography variant="subtitle2">Standard Fields</Typography>
                      {STANDARD_FIELDS.map((field) => {
                        const editableBy = perm.standard_fields[field.key]?.editable_by ?? [];
                        return (
                          <Box key={field.key} sx={{ ml: 1, mt: 0.5 }}>
                            <Typography variant="body2" component="span">
                              {field.label}
                              {field.mandatory ? ' *' : ''}
                            </Typography>
                            <Box
                              sx={{
                                ml: 1,
                                mt: 0.25,
                                display: 'flex',
                                gap: 0.5,
                                flexWrap: 'wrap',
                                alignItems: 'center',
                              }}
                            >
                              {editableBy.length === 0 ? (
                                <Typography variant="caption" color="text.disabled">
                                  read-only in this state
                                </Typography>
                              ) : null}
                              {ALL_ROLES.map((role) => (
                                <Chip
                                  key={role}
                                  label={role}
                                  size="small"
                                  clickable
                                  color={editableBy.includes(role) ? 'primary' : 'default'}
                                  variant={editableBy.includes(role) ? 'filled' : 'outlined'}
                                  onClick={() => handleToggleRole(stateKey, field.key, role)}
                                />
                              ))}
                            </Box>
                          </Box>
                        );
                      })}
                    </Box>

                    {/* Custom Fields */}
                    {customFieldDefs.length > 0 && (
                      <Box sx={{ mt: 1 }}>
                        <Typography variant="subtitle2">Custom Fields</Typography>
                        {customFieldDefs.map((defn) => {
                          const included = defn.field_key in cfPerms;
                          const editableBy = cfPerms[defn.field_key]?.editable_by ?? [];
                          return (
                            <Box key={defn.field_key} sx={{ ml: 1, mt: 0.5 }}>
                              <FormControlLabel
                                control={
                                  <Checkbox
                                    size="small"
                                    checked={included}
                                    onChange={(e) => {
                                      setFieldPerms((fp) => {
                                        const statePerm = fp[stateKey] ?? {
                                          standard_fields: {},
                                          custom_fields: {},
                                        };
                                        const cf = { ...statePerm.custom_fields };
                                        if (e.target.checked) {
                                          cf[defn.field_key] = { editable_by: [] };
                                        } else {
                                          delete cf[defn.field_key];
                                        }
                                        return {
                                          ...fp,
                                          [stateKey]: { ...statePerm, custom_fields: cf },
                                        };
                                      });
                                    }}
                                  />
                                }
                                label={defn.label}
                              />
                              {included && (
                                <Box
                                  sx={{
                                    ml: 3,
                                    display: 'flex',
                                    gap: 0.5,
                                    flexWrap: 'wrap',
                                    mb: 0.5,
                                  }}
                                >
                                  {ALL_ROLES.map((role) => (
                                    <Chip
                                      key={role}
                                      label={role}
                                      size="small"
                                      clickable
                                      color={editableBy.includes(role) ? 'primary' : 'default'}
                                      variant={editableBy.includes(role) ? 'filled' : 'outlined'}
                                      onClick={() => {
                                        setFieldPerms((fp) => {
                                          const statePerm = fp[stateKey] ?? {
                                            standard_fields: {},
                                            custom_fields: {},
                                          };
                                          const cf = { ...statePerm.custom_fields };
                                          const current = cf[defn.field_key]?.editable_by ?? [];
                                          cf[defn.field_key] = {
                                            editable_by: current.includes(role)
                                              ? current.filter((r) => r !== role)
                                              : [...current, role],
                                          };
                                          return {
                                            ...fp,
                                            [stateKey]: { ...statePerm, custom_fields: cf },
                                          };
                                        });
                                      }}
                                    />
                                  ))}
                                </Box>
                              )}
                            </Box>
                          );
                        })}
                      </Box>
                    )}
                  </Box>
                );
              })
            )}
          </Box>

          {/* Enterprise-only: Admission Lockdown */}
          {appliesToKind === 'enterprise' && (
            <>
              <Divider />
              <FormControl sx={{ mt: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Admission lockdown state
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ mb: 1 }}>
                  When the release is in this state, new membership admissions are blocked.
                </Typography>
                <RadioGroup
                  value={states.find((s) => s.is_admission_lockdown)?.key ?? ''}
                  onChange={(e) => setLockdownKey(e.target.value)}
                >
                  {states
                    .filter((s) => s.key.trim())
                    .map((s) => (
                      <FormControlLabel
                        key={s.key}
                        value={s.key}
                        control={<Radio size="small" />}
                        label={s.label || s.key}
                      />
                    ))}
                </RadioGroup>
              </FormControl>
            </>
          )}

          {/* Enterprise-only: Admission Permissions matrix */}
          {appliesToKind === 'enterprise' && (
            <>
              <Divider />
              <Box sx={{ mt: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Admission permissions
                </Typography>
                <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
                  Which roles may admit, reject, or remove members when the release is in each
                  non-terminal state.
                </Typography>
                {states.filter((s) => s.key.trim() && !s.is_terminal).length === 0 ? (
                  <Typography variant="body2" color="text.secondary">
                    Add non-terminal states first.
                  </Typography>
                ) : (
                  states
                    .filter((s) => s.key.trim() && !s.is_terminal)
                    .map((s) => (
                      <Paper key={s.key} variant="outlined" sx={{ p: 1.5, my: 1 }}>
                        <Typography variant="body2" fontWeight="bold" sx={{ mb: 1 }}>
                          {s.label || s.key}
                        </Typography>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell>Role</TableCell>
                              <TableCell align="center">Admit</TableCell>
                              <TableCell align="center">Reject</TableCell>
                              <TableCell align="center">Remove</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {ALL_ROLES.map((role) => (
                              <TableRow key={role}>
                                <TableCell>{role}</TableCell>
                                {(
                                  [
                                    'membership.admit',
                                    'membership.reject',
                                    'membership.remove',
                                  ] as const
                                ).map((action) => (
                                  <TableCell key={action} align="center" padding="checkbox">
                                    <Checkbox
                                      size="small"
                                      checked={(
                                        actionPermissions[s.key]?.[action] ?? []
                                      ).includes(role)}
                                      onChange={(e) =>
                                        toggleActionPermission(s.key, action, role, e.target.checked)
                                      }
                                    />
                                  </TableCell>
                                ))}
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </Paper>
                    ))
                )}
              </Box>
            </>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button variant="contained" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving...' : editTemplateId !== null ? 'Save Changes' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
