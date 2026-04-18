# Booking Admin Lifecycle Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move booking configuration into the existing Admin → Bookings "Lifecycle" tab and add a structured form for creating lifecycle templates from scratch.

**Architecture:** Extract `BookingConfiguration.tsx` into two focused panel components (`BookingTypesPanel`, `LifecycleTemplatesPanel`), wire them into the already-existing (but disabled) Lifecycle tab in `EntityConfig`, and delete the old hidden route. The `LifecycleTemplatesPanel` gains a new "New Template" dialog with inline state/transition row editing. No backend changes required.

**Tech Stack:** React 18, TypeScript, MUI v5, Redux Toolkit, React Router DOM.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Delete | `frontend/src/pages/admin/BookingConfiguration.tsx` | Replaced by two panels |
| Create | `frontend/src/components/admin/BookingTypesPanel.tsx` | Booking types DataGrid + New Type dialog |
| Create | `frontend/src/components/admin/LifecycleTemplatesPanel.tsx` | Templates DataGrid + New Template dialog |
| Modify | `frontend/src/pages/admin/EntityConfig.tsx` | Enable Lifecycle tab for booking, render panels |
| Modify | `frontend/src/App.tsx` | Remove `/tenant/booking-config` route + import |
| Modify | `frontend/src/components/AppLayout.tsx` | Remove "Booking Config" menu item |

---

## Task 1: Remove old route and navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`

- [ ] **Step 1: Remove the `/tenant/booking-config` route and its import from App.tsx**

In `frontend/src/App.tsx`, remove:
```tsx
import BookingConfiguration from './pages/admin/BookingConfiguration'
```
And remove the entire route block:
```tsx
<Route
    path="/tenant/booking-config"
    element={<PrivateRoute requiredRole="Admin"><BookingConfiguration /></PrivateRoute>}
/>
```

- [ ] **Step 2: Remove "Booking Config" menu item from AppLayout.tsx**

In `frontend/src/components/AppLayout.tsx`, remove the entire block:
```tsx
{user?.role === 'Admin' && (
    <MenuItem onClick={() => handleMenuNav('/tenant/booking-config')}>
        <ListItemIcon><AdminPanelSettingsIcon fontSize="small" /></ListItemIcon>
        <ListItemText>Booking Config</ListItemText>
    </MenuItem>
)}
```

- [ ] **Step 3: Delete BookingConfiguration.tsx**

```bash
rm frontend/src/pages/admin/BookingConfiguration.tsx
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/AppLayout.tsx
git commit -m "refactor: remove standalone booking-config route and menu item"
```

---

## Task 2: Create BookingTypesPanel

**Files:**
- Create: `frontend/src/components/admin/BookingTypesPanel.tsx`

This is a straight extraction of the booking types section from `BookingConfiguration.tsx`. The `BookingTypesPanel` dispatches both `fetchBookingTypes` and `fetchLifecycleTemplates` on mount because it needs templates for the "New Type" dialog dropdown.

- [ ] **Step 1: Create the file**

Create `frontend/src/components/admin/BookingTypesPanel.tsx` with this content:

```tsx
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box, Button, Typography, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, MenuItem, Alert,
} from '@mui/material';
import { DataGrid } from '@mui/x-data-grid';
import type { GridColDef } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import {
  fetchBookingTypes,
  fetchLifecycleTemplates,
  createBookingType,
} from '../../store/bookingLifecycleSlice';

export default function BookingTypesPanel() {
  const dispatch = useDispatch<AppDispatch>();
  const { templates, bookingTypes, loading } = useSelector((s: RootState) => s.bookingLifecycle);

  const [createTypeOpen, setCreateTypeOpen] = useState(false);
  const [newTypeName, setNewTypeName] = useState('');
  const [newTypeTemplateId, setNewTypeTemplateId] = useState<number | ''>('');
  const [createTypeError, setCreateTypeError] = useState<string | null>(null);

  useEffect(() => {
    dispatch(fetchBookingTypes());
    dispatch(fetchLifecycleTemplates());
  }, [dispatch]);

  const handleCreateType = async () => {
    if (!newTypeName || !newTypeTemplateId) return;
    setCreateTypeError(null);
    const result = await dispatch(createBookingType({
      name: newTypeName,
      lifecycle_template_id: Number(newTypeTemplateId),
      is_active: true,
      description: null,
      color: null,
    }));
    if (createBookingType.rejected.match(result)) {
      setCreateTypeError(result.error.message ?? 'Failed to create booking type');
      return;
    }
    setCreateTypeOpen(false);
    setNewTypeName('');
    setNewTypeTemplateId('');
  };

  const columns: GridColDef[] = [
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

  return (
    <Box sx={{ mb: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Booking Types</Typography>
        <Button variant="contained" size="small" onClick={() => setCreateTypeOpen(true)}>
          + New Type
        </Button>
      </Box>

      <DataGrid
        rows={bookingTypes}
        columns={columns}
        loading={loading}
        autoHeight
        disableRowSelectionOnClick
        pageSizeOptions={[10, 25]}
      />

      <Dialog open={createTypeOpen} onClose={() => setCreateTypeOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>New Booking Type</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
          {createTypeError && <Alert severity="error">{createTypeError}</Alert>}
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
    </Box>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/BookingTypesPanel.tsx
git commit -m "feat: extract BookingTypesPanel component"
```

---

## Task 3: Create LifecycleTemplatesPanel

**Files:**
- Create: `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`

This is the complex task. It includes: the templates DataGrid with Copy row action, and a "New Template" dialog with inline editable state rows and transition rows.

The dialog manages two lists:
- `StateRow`: `{ key, label, is_initial, is_terminal }`
- `TransitionRow`: `{ from_state, to_state, label, allowed_roles }`

Validation runs on submit (not on change). The allowed roles are: `Admin`, `Release Manager`, `Test Manager`, `Developer`, `Viewer`.

The create payload shape:
```ts
{
  name, description, is_default: false,
  definition: { states, transitions, field_permissions: {} }
}
```

- [ ] **Step 1: Create the file**

Create `frontend/src/components/admin/LifecycleTemplatesPanel.tsx`:

```tsx
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
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/admin/LifecycleTemplatesPanel.tsx
git commit -m "feat: add LifecycleTemplatesPanel with New Template creation dialog"
```

---

## Task 4: Wire panels into EntityConfig

**Files:**
- Modify: `frontend/src/pages/admin/EntityConfig.tsx`

Enable the Lifecycle tab for `entityType === 'booking'` and render the two panels inside it.

- [ ] **Step 1: Update EntityConfig.tsx**

Replace the entire content of `frontend/src/pages/admin/EntityConfig.tsx` with:

```tsx
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { Box, Chip, Divider, Tab, Tabs, Typography } from '@mui/material';
import CustomFieldDefinitionManager from '../../components/admin/CustomFieldDefinitionManager';
import BookingTypesPanel from '../../components/admin/BookingTypesPanel';
import LifecycleTemplatesPanel from '../../components/admin/LifecycleTemplatesPanel';
import type { EntityType } from '../../types/customField';

const ENTITY_LABELS: Record<string, string> = {
  system: 'Systems',
  subsystem: 'Subsystems',
  environment: 'Environments',
  booking: 'Bookings',
};

export default function EntityConfig() {
  const { entityType } = useParams<{ entityType: string }>();
  const [tab, setTab] = useState(0);

  if (!entityType || !ENTITY_LABELS[entityType]) {
    return <Typography>Unknown entity type.</Typography>;
  }

  const et = entityType as EntityType;
  const isBooking = et === 'booking';

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>{ENTITY_LABELS[et]} Configuration</Typography>
      <Typography color="text.secondary" sx={{ mb: 3 }}>
        Configure custom fields and other {ENTITY_LABELS[et].toLowerCase()} settings for your tenant.
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)}>
          <Tab label="Custom Fields" />
          {isBooking ? (
            <Tab label="Lifecycle" />
          ) : (
            <Tab
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  Lifecycle <Chip label="Coming Soon" size="small" />
                </Box>
              }
              disabled
            />
          )}
        </Tabs>
      </Box>

      {tab === 0 && <CustomFieldDefinitionManager entityType={et} />}

      {tab === 1 && isBooking && (
        <Box>
          <BookingTypesPanel />
          <Divider sx={{ my: 3 }} />
          <LifecycleTemplatesPanel />
        </Box>
      )}
    </Box>
  );
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit
```
Expected: no errors.

- [ ] **Step 3: Verify manually**

Navigate to `/admin/config/booking` in the browser. Confirm:
- "Custom Fields" tab works as before
- "Lifecycle" tab is now enabled (no "Coming Soon" chip)
- Clicking "Lifecycle" shows Booking Types DataGrid + Lifecycle Templates DataGrid
- "New Type" dialog opens and can create a type
- "New Template" dialog opens with States and Transitions sections
- Adding states populates the From/To dropdowns in Transitions
- Roles toggle correctly on click
- Creating a template with valid data adds it to the grid
- Validation errors show inline (try submitting with no states, or two initial states)
- Navigate to `/admin/config/system` — Lifecycle tab still shows "Coming Soon" and is disabled

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/admin/EntityConfig.tsx
git commit -m "feat: enable Lifecycle tab in booking admin with types and template panels"
```

---

## Verification Checklist

- [ ] `/tenant/booking-config` returns 404 (route removed)
- [ ] "Booking Config" no longer appears in the user dropdown menu
- [ ] `/admin/config/booking` Lifecycle tab is enabled and shows both panels
- [ ] `/admin/config/system` Lifecycle tab is still disabled with "Coming Soon"
- [ ] Booking Types DataGrid loads and "New Type" creates a type
- [ ] Lifecycle Templates DataGrid loads and "Copy" creates a copy
- [ ] "New Template" with valid states + transitions creates a new template
- [ ] Validation rejects: no states, two initial states, duplicate state keys, transition with no roles
- [ ] TypeScript: `npx tsc --noEmit` exits clean
