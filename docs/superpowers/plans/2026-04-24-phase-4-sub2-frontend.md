# Phase 4 Sub-2 — Frontend + API Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the UI surface for Phase 4 — API key admin page, top-level Build + Deployment list/detail pages, Deployments tabs on EnvironmentDetail + ReleaseDetail, deployments rendered on EnvironmentSchedule, and a link-change dialog. One backend tweak (schedule helper returns `build_sha_short`).

**Architecture:** React 18 + TS + MUI + Redux Toolkit, following the Phase 3 patterns (service modules, slice per entity, pages for list/detail, dialogs as reusable components). No new top-level routing primitives — we add routes to the existing router in `App.tsx`. FullCalendar used on EnvironmentSchedule for deployment rendering; same `scheduleService.getEnvironmentSchedule` response extended to include deployments with denormalised `build_sha_short`.

**Tech Stack:** React 18, TypeScript strict, MUI v5, Redux Toolkit, FullCalendar, Vitest.

**Spec:** `docs/superpowers/specs/2026-04-24-phase-4-sub2-frontend-design.md`

**Working directory:** Feature branch `feature/phase-4-sub2-frontend` off `main` tip `d23bd7f`. Run frontend commands from `frontend/`; backend commands from `backend/`.

---

## Task 1: Frontend types

**Files:**
- Create: `frontend/src/types/apiKey.ts`
- Create: `frontend/src/types/build.ts`
- Create: `frontend/src/types/deployment.ts`

- [ ] **Step 1: Create `apiKey.ts`**

```typescript
// frontend/src/types/apiKey.ts
export interface ApiKey {
  id: number;
  name: string;
  scopes: string[];
  created_by: number;
  created_by_username: string | null;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface ApiKeyCreatePayload {
  name: string;
  scopes: string[];
  expires_at?: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  raw_key: string;
}
```

- [ ] **Step 2: Create `build.ts`**

```typescript
// frontend/src/types/build.ts
export interface PipelineStep {
  name: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Build {
  id: number;
  tenant_id: number;
  subsystem_id: number;
  release_id: number | null;
  git_sha: string;
  git_branch: string | null;
  build_number: string | null;
  commit_timestamp: string;
  build_started_at: string | null;
  build_finished_at: string | null;
  jira_tickets: string[];
  pipeline_steps: PipelineStep[];
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface BuildFilters {
  subsystem_id?: number;
  release_id?: number;
  branch?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}
```

- [ ] **Step 3: Create `deployment.ts`**

```typescript
// frontend/src/types/deployment.ts
export type DeploymentStatus =
  | 'pending'
  | 'in_progress'
  | 'success'
  | 'failed'
  | 'rolled_back';

export interface Deployment {
  id: number;
  tenant_id: number;
  build_id: number;
  environment_id: number;
  release_id: number | null;
  change_request_id: number;
  event_id: string;
  deployer_name: string | null;
  deployed_at: string;
  completed_at: string | null;
  status: DeploymentStatus;
  custom_fields: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DeploymentFilters {
  environment_id?: number;
  release_id?: number;
  build_id?: number;
  status?: DeploymentStatus;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface DeploymentLinkChangeRequest {
  change_request_id: number;
}
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/apiKey.ts frontend/src/types/build.ts frontend/src/types/deployment.ts
git commit -m "feat(phase-4-ui): add apiKey + build + deployment types"
```

---

## Task 2: Frontend services

**Files:**
- Create: `frontend/src/services/apiKeyService.ts`
- Create: `frontend/src/services/buildService.ts`
- Create: `frontend/src/services/deploymentService.ts`

- [ ] **Step 1: `apiKeyService.ts`**

```typescript
// frontend/src/services/apiKeyService.ts
import api from './api';
import type { ApiKey, ApiKeyCreatePayload, ApiKeyCreated } from '../types/apiKey';

export const apiKeyService = {
  list: (): Promise<ApiKey[]> =>
    api.get<ApiKey[]>('/api-keys').then((r) => r.data),
  create: (data: ApiKeyCreatePayload): Promise<ApiKeyCreated> =>
    api.post<ApiKeyCreated>('/api-keys', data).then((r) => r.data),
  revoke: (id: number): Promise<void> =>
    api.delete(`/api-keys/${id}`).then(() => undefined),
};
```

- [ ] **Step 2: `buildService.ts`**

```typescript
// frontend/src/services/buildService.ts
import api from './api';
import type { Build, BuildFilters } from '../types/build';

function toParams(filters: BuildFilters | undefined): Record<string, string | number> {
  if (!filters) return {};
  const out: Record<string, string | number> = {};
  if (filters.subsystem_id !== undefined) out.subsystem_id = filters.subsystem_id;
  if (filters.release_id !== undefined) out.release_id = filters.release_id;
  if (filters.branch) out.branch = filters.branch;
  if (filters.date_from) out.date_from = filters.date_from;
  if (filters.date_to) out.date_to = filters.date_to;
  if (filters.limit !== undefined) out.limit = filters.limit;
  if (filters.offset !== undefined) out.offset = filters.offset;
  return out;
}

export const buildService = {
  list: (filters?: BuildFilters): Promise<Build[]> =>
    api.get<Build[]>('/builds', { params: toParams(filters) }).then((r) => r.data),
  get: (id: number): Promise<Build> =>
    api.get<Build>(`/builds/${id}`).then((r) => r.data),
};
```

- [ ] **Step 3: `deploymentService.ts`**

```typescript
// frontend/src/services/deploymentService.ts
import api from './api';
import type {
  Deployment,
  DeploymentFilters,
  DeploymentLinkChangeRequest,
} from '../types/deployment';

function toParams(filters: DeploymentFilters | undefined): Record<string, string | number> {
  if (!filters) return {};
  const out: Record<string, string | number> = {};
  if (filters.environment_id !== undefined) out.environment_id = filters.environment_id;
  if (filters.release_id !== undefined) out.release_id = filters.release_id;
  if (filters.build_id !== undefined) out.build_id = filters.build_id;
  if (filters.status) out.status = filters.status;
  if (filters.date_from) out.date_from = filters.date_from;
  if (filters.date_to) out.date_to = filters.date_to;
  if (filters.limit !== undefined) out.limit = filters.limit;
  if (filters.offset !== undefined) out.offset = filters.offset;
  return out;
}

export const deploymentService = {
  list: (filters?: DeploymentFilters): Promise<Deployment[]> =>
    api.get<Deployment[]>('/deployments', { params: toParams(filters) }).then((r) => r.data),
  get: (id: number): Promise<Deployment> =>
    api.get<Deployment>(`/deployments/${id}`).then((r) => r.data),
  linkChange: (id: number, data: DeploymentLinkChangeRequest): Promise<Deployment> =>
    api.post<Deployment>(`/deployments/${id}/link-change`, data).then((r) => r.data),
  forEnvironment: (envId: number): Promise<Deployment[]> =>
    api.get<Deployment[]>(`/environments/${envId}/deployments`).then((r) => r.data),
};
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/apiKeyService.ts frontend/src/services/buildService.ts frontend/src/services/deploymentService.ts
git commit -m "feat(phase-4-ui): add apiKey + build + deployment service clients"
```

---

## Task 3: Redux slices

**Files:**
- Create: `frontend/src/store/apiKeySlice.ts`
- Create: `frontend/src/store/buildSlice.ts`
- Create: `frontend/src/store/deploymentSlice.ts`
- Modify: `frontend/src/store/index.ts` — register the three reducers

- [ ] **Step 1: `apiKeySlice.ts`**

```typescript
// frontend/src/store/apiKeySlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { apiKeyService } from '../services/apiKeyService';
import type { ApiKey, ApiKeyCreatePayload, ApiKeyCreated } from '../types/apiKey';

interface ApiKeyState {
  items: ApiKey[];
  loading: boolean;
  error: string | null;
  justCreated: ApiKeyCreated | null;
}

const initialState: ApiKeyState = {
  items: [],
  loading: false,
  error: null,
  justCreated: null,
};

export const fetchApiKeys = createAsyncThunk('apiKey/fetch', () => apiKeyService.list());
export const createApiKey = createAsyncThunk(
  'apiKey/create',
  (data: ApiKeyCreatePayload) => apiKeyService.create(data),
);
export const revokeApiKey = createAsyncThunk(
  'apiKey/revoke',
  async (id: number) => {
    await apiKeyService.revoke(id);
    return id;
  },
);

const slice = createSlice({
  name: 'apiKey',
  initialState,
  reducers: {
    clearJustCreated(state) {
      state.justCreated = null;
    },
  },
  extraReducers: (b) => {
    b.addCase(fetchApiKeys.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchApiKeys.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchApiKeys.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load API keys';
    });
    b.addCase(createApiKey.fulfilled, (s, a) => {
      s.justCreated = a.payload;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { raw_key, ...rest } = a.payload;
      s.items = [rest, ...s.items];
    });
    b.addCase(revokeApiKey.fulfilled, (s, a) => {
      s.items = s.items.filter((k) => k.id !== a.payload);
    });
  },
});

export const { clearJustCreated } = slice.actions;
export default slice.reducer;
```

- [ ] **Step 2: `buildSlice.ts`**

```typescript
// frontend/src/store/buildSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { buildService } from '../services/buildService';
import type { Build, BuildFilters } from '../types/build';

interface BuildState {
  items: Build[];
  current: Build | null;
  loading: boolean;
  error: string | null;
}

const initialState: BuildState = {
  items: [],
  current: null,
  loading: false,
  error: null,
};

export const fetchBuilds = createAsyncThunk('build/fetch', (filters?: BuildFilters) =>
  buildService.list(filters),
);
export const fetchBuildById = createAsyncThunk('build/fetchById', (id: number) =>
  buildService.get(id),
);

const slice = createSlice({
  name: 'build',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchBuilds.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchBuilds.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchBuilds.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load builds';
    });
    b.addCase(fetchBuildById.fulfilled, (s, a) => { s.current = a.payload; });
  },
});

export default slice.reducer;
```

- [ ] **Step 3: `deploymentSlice.ts`**

```typescript
// frontend/src/store/deploymentSlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { deploymentService } from '../services/deploymentService';
import type {
  Deployment,
  DeploymentFilters,
  DeploymentLinkChangeRequest,
} from '../types/deployment';

interface DeploymentState {
  items: Deployment[];
  current: Deployment | null;
  loading: boolean;
  error: string | null;
}

const initialState: DeploymentState = {
  items: [],
  current: null,
  loading: false,
  error: null,
};

export const fetchDeployments = createAsyncThunk(
  'deployment/fetch',
  (filters?: DeploymentFilters) => deploymentService.list(filters),
);
export const fetchDeploymentById = createAsyncThunk(
  'deployment/fetchById',
  (id: number) => deploymentService.get(id),
);
export const linkDeploymentChange = createAsyncThunk(
  'deployment/linkChange',
  (args: { id: number; data: DeploymentLinkChangeRequest }) =>
    deploymentService.linkChange(args.id, args.data),
);

const slice = createSlice({
  name: 'deployment',
  initialState,
  reducers: {},
  extraReducers: (b) => {
    b.addCase(fetchDeployments.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchDeployments.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchDeployments.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load deployments';
    });
    b.addCase(fetchDeploymentById.fulfilled, (s, a) => { s.current = a.payload; });
    b.addCase(linkDeploymentChange.fulfilled, (s, a) => {
      s.current = a.payload;
      s.items = s.items.map((d) => (d.id === a.payload.id ? a.payload : d));
    });
  },
});

export default slice.reducer;
```

- [ ] **Step 4: Register in `frontend/src/store/index.ts`**

Open the file. Add the imports next to existing slice imports:

```typescript
import apiKeyReducer from './apiKeySlice';
import buildReducer from './buildSlice';
import deploymentReducer from './deploymentSlice';
```

In the `configureStore({ reducer: { ... } })` call, add the three keys:

```typescript
    apiKey: apiKeyReducer,
    build: buildReducer,
    deployment: deploymentReducer,
```

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/apiKeySlice.ts frontend/src/store/buildSlice.ts frontend/src/store/deploymentSlice.ts frontend/src/store/index.ts
git commit -m "feat(phase-4-ui): redux slices for apiKey + build + deployment"
```

---

## Task 4: `DeploymentStatusChip` shared component

**Files:**
- Create: `frontend/src/components/deployments/DeploymentStatusChip.tsx`
- Create: `frontend/src/components/deployments/__tests__/DeploymentStatusChip.test.tsx`

- [ ] **Step 1: Write the component**

`frontend/src/components/deployments/DeploymentStatusChip.tsx`:

```tsx
import { Chip } from '@mui/material';
import type { DeploymentStatus } from '../../types/deployment';

const COLORS: Record<DeploymentStatus, string> = {
  pending: '#607d8b',
  in_progress: '#607d8b',
  success: '#43a047',
  failed: '#e53935',
  rolled_back: '#ffb300',
};

const LABELS: Record<DeploymentStatus, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  success: 'Success',
  failed: 'Failed',
  rolled_back: 'Rolled back',
};

interface Props {
  status: DeploymentStatus;
  size?: 'small' | 'medium';
}

export default function DeploymentStatusChip({ status, size = 'small' }: Props) {
  return (
    <Chip
      label={LABELS[status]}
      size={size}
      sx={{ backgroundColor: COLORS[status], color: 'white', fontWeight: 500 }}
    />
  );
}
```

- [ ] **Step 2: Write component tests**

`frontend/src/components/deployments/__tests__/DeploymentStatusChip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DeploymentStatusChip from '../DeploymentStatusChip';

describe('DeploymentStatusChip', () => {
  it.each([
    ['pending', 'Pending'],
    ['in_progress', 'In progress'],
    ['success', 'Success'],
    ['failed', 'Failed'],
    ['rolled_back', 'Rolled back'],
  ] as const)('renders %s with label %s', (status, label) => {
    render(<DeploymentStatusChip status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend && npx vitest run src/components/deployments/__tests__/DeploymentStatusChip.test.tsx
```

Expected: 5 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/deployments/DeploymentStatusChip.tsx frontend/src/components/deployments/__tests__/DeploymentStatusChip.test.tsx
git commit -m "feat(phase-4-ui): DeploymentStatusChip with palette tests"
```

---

## Task 5: API key dialogs

**Files:**
- Create: `frontend/src/components/apikeys/ApiKeyCreateDialog.tsx`
- Create: `frontend/src/components/apikeys/ApiKeyCreatedDialog.tsx`
- Create: `frontend/src/components/apikeys/__tests__/ApiKeyCreatedDialog.test.tsx`

- [ ] **Step 1: Create `ApiKeyCreateDialog`**

```tsx
// frontend/src/components/apikeys/ApiKeyCreateDialog.tsx
import { useState } from 'react';
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Stack, TextField, Typography,
} from '@mui/material';
import type { ApiKeyCreatePayload } from '../../types/apiKey';

const AVAILABLE_SCOPES = [
  { key: 'webhooks:deployment', label: 'CI/CD deployment webhook' },
] as const;

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: ApiKeyCreatePayload) => Promise<void>;
}

export default function ApiKeyCreateDialog({ open, onClose, onSubmit }: Props) {
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['webhooks:deployment']);
  const [expiresAt, setExpiresAt] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    if (submitting) return;
    setName('');
    setScopes(['webhooks:deployment']);
    setExpiresAt('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const iso = expiresAt ? new Date(`${expiresAt}T00:00:00Z`).toISOString() : null;
      await onSubmit({ name: name.trim(), scopes, expires_at: iso });
      handleClose();
    } finally {
      setSubmitting(false);
    }
  };

  const toggleScope = (key: string) => {
    setScopes((prev) => (prev.includes(key) ? prev.filter((s) => s !== key) : [...prev, key]));
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>New API key</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Name" required fullWidth autoFocus
            value={name} onChange={(e) => setName(e.target.value)}
            inputProps={{ maxLength: 120 }}
          />
          <Box>
            <Typography variant="overline" color="text.secondary">Scopes</Typography>
            {AVAILABLE_SCOPES.map((s) => (
              <FormControlLabel
                key={s.key}
                control={
                  <Checkbox
                    checked={scopes.includes(s.key)}
                    onChange={() => toggleScope(s.key)}
                  />
                }
                label={`${s.label} (${s.key})`}
                sx={{ display: 'block' }}
              />
            ))}
          </Box>
          <TextField
            label="Expires at (optional)"
            type="date"
            fullWidth
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!name.trim() || submitting || scopes.length === 0}
        >
          Create
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 2: Create `ApiKeyCreatedDialog`**

```tsx
// frontend/src/components/apikeys/ApiKeyCreatedDialog.tsx
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, Stack, TextField, Tooltip,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useState } from 'react';

interface Props {
  open: boolean;
  rawKey: string;
  onDismiss: () => void;
}

export default function ApiKeyCreatedDialog({ open, rawKey, onDismiss }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} disableEscapeKeyDown maxWidth="sm" fullWidth>
      <DialogTitle>API key created</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Alert severity="warning">
            This is the only time you will see this key. Copy it somewhere
            secure — you will not be able to retrieve it again.
          </Alert>
          <Stack direction="row" spacing={1} alignItems="center">
            <TextField
              fullWidth
              value={rawKey}
              inputProps={{ readOnly: true, style: { fontFamily: 'monospace' } }}
            />
            <Tooltip title={copied ? 'Copied!' : 'Copy to clipboard'}>
              <IconButton onClick={handleCopy} aria-label="copy">
                <ContentCopyIcon />
              </IconButton>
            </Tooltip>
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={onDismiss}>
          I've copied it
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

- [ ] **Step 3: Write test for `ApiKeyCreatedDialog`**

`frontend/src/components/apikeys/__tests__/ApiKeyCreatedDialog.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ApiKeyCreatedDialog from '../ApiKeyCreatedDialog';

describe('ApiKeyCreatedDialog', () => {
  it('renders the raw key', () => {
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={() => {}} />,
    );
    expect(screen.getByDisplayValue('em_abc123')).toBeInTheDocument();
  });

  it('calls navigator.clipboard.writeText on copy click', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={() => {}} />,
    );
    fireEvent.click(screen.getByLabelText('copy'));
    expect(writeText).toHaveBeenCalledWith('em_abc123');
  });

  it('calls onDismiss when the button is clicked', () => {
    const onDismiss = vi.fn();
    render(
      <ApiKeyCreatedDialog open rawKey="em_abc123" onDismiss={onDismiss} />,
    );
    fireEvent.click(screen.getByText("I've copied it"));
    expect(onDismiss).toHaveBeenCalled();
  });
});
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npx vitest run src/components/apikeys/__tests__/
```

Expected: 3 passed.

- [ ] **Step 5: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/apikeys/
git commit -m "feat(phase-4-ui): ApiKeyCreateDialog + ApiKeyCreatedDialog (raw key shown once)"
```

---

## Task 6: `ApiKeyManagement` admin page

**Files:**
- Create: `frontend/src/pages/admin/ApiKeyManagement.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx` — add nav entry
- Modify: `frontend/src/App.tsx` — add route

- [ ] **Step 1: Create the page**

`frontend/src/pages/admin/ApiKeyManagement.tsx`:

```tsx
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Box, Button, Chip, IconButton, Paper, Stack, Tooltip, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { DataGrid, GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import { useState } from 'react';
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
import type { ApiKeyCreatePayload } from '../../types/apiKey';

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

  const handleRevoke = async (id: number) => {
    if (!(await confirm({ message: 'Revoke this API key?', destructive: true }))) return;
    try {
      await dispatch(revokeApiKey(id)).unwrap();
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
      valueGetter: (v) => (v ? new Date(v).toLocaleString() : '—'),
    },
    {
      field: 'expires_at', headerName: 'Expires', width: 140,
      valueGetter: (v) => (v ? new Date(v).toLocaleDateString() : 'Never'),
    },
    {
      field: 'actions', headerName: '', width: 80, sortable: false,
      renderCell: (p) => (
        <Tooltip title="Revoke">
          <IconButton size="small" color="error" onClick={() => handleRevoke(p.row.id)}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ),
    },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 2 }}>
        <Typography variant="h5">API keys</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
          New key
        </Button>
      </Stack>

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
```

- [ ] **Step 2: Add admin drawer nav entry**

In `frontend/src/pages/admin/AdminLayout.tsx`, locate the `adminNavItems` array (the first one, with `SettingsIcon` / `PeopleIcon`). Add a new entry:

```typescript
import VpnKeyIcon from '@mui/icons-material/VpnKey';

// Inside adminNavItems:
  { label: 'API keys', path: '/tenant/api-keys', icon: <VpnKeyIcon fontSize="small" /> },
```

- [ ] **Step 3: Register the route**

In `frontend/src/App.tsx`, find the existing `/tenant/settings` or `/tenant/users` route block (wrapped in `<PrivateRoute requiredRole="Admin">`) and add a sibling for the new page:

```tsx
import ApiKeyManagement from './pages/admin/ApiKeyManagement';

// Inside the tenant admin routes:
<Route
  path="/tenant/api-keys"
  element={
    <PrivateRoute requiredRole="Admin">
      <AdminLayout />
    </PrivateRoute>
  }
>
  <Route index element={<ApiKeyManagement />} />
</Route>
```

Match the existing routing pattern exactly — read the adjacent routes first.

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/admin/ApiKeyManagement.tsx frontend/src/pages/admin/AdminLayout.tsx frontend/src/App.tsx
git commit -m "feat(phase-4-ui): ApiKeyManagement admin page + route"
```

---

## Task 7: `BuildList` page + top-level nav

**Files:**
- Create: `frontend/src/pages/builds/BuildList.tsx`
- Modify: `frontend/src/components/AppLayout.tsx` — add top-level Builds nav entry
- Modify: `frontend/src/App.tsx` — add route

- [ ] **Step 1: Create the page**

`frontend/src/pages/builds/BuildList.tsx`:

```tsx
import { useEffect, useState, useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Box, Paper, Stack, TextField, Typography } from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchBuilds } from '../../store/buildSlice';
import type { BuildFilters, PipelineStep } from '../../types/build';

function latestStepSummary(steps: PipelineStep[]): string {
  if (steps.length === 0) return '—';
  const last = steps[steps.length - 1];
  return `${last.name} (${last.status})`;
}

export default function BuildList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.build);

  const [subsystemId, setSubsystemId] = useState('');
  const [branch, setBranch] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const filters = useMemo<BuildFilters>(() => {
    const f: BuildFilters = {};
    if (subsystemId) f.subsystem_id = Number(subsystemId);
    if (branch) f.branch = branch;
    if (dateFrom) f.date_from = new Date(`${dateFrom}T00:00:00Z`).toISOString();
    if (dateTo) f.date_to = new Date(`${dateTo}T23:59:59Z`).toISOString();
    return f;
  }, [subsystemId, branch, dateFrom, dateTo]);

  useEffect(() => {
    dispatch(fetchBuilds(filters));
  }, [dispatch, filters]);

  const rows = items.map((b) => ({
    id: b.id,
    subsystem_id: b.subsystem_id,
    git_sha_short: b.git_sha.slice(0, 8),
    git_branch: b.git_branch ?? '—',
    build_number: b.build_number ?? '—',
    commit_timestamp: new Date(b.commit_timestamp).toLocaleString(),
    latest_step: latestStepSummary(b.pipeline_steps),
  }));

  const cols: GridColDef[] = [
    { field: 'subsystem_id', headerName: 'SubSystem', width: 120 },
    { field: 'git_branch', headerName: 'Branch', width: 160 },
    { field: 'git_sha_short', headerName: 'SHA', width: 100 },
    { field: 'build_number', headerName: 'Build #', width: 100 },
    { field: 'commit_timestamp', headerName: 'Commit at', width: 200 },
    { field: 'latest_step', headerName: 'Latest step', flex: 1 },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Builds</Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="Subsystem id"
            value={subsystemId} onChange={(e) => setSubsystemId(e.target.value)}
            sx={{ width: 140 }} type="number"
          />
          <TextField
            size="small" label="Branch"
            value={branch} onChange={(e) => setBranch(e.target.value)}
            sx={{ width: 180 }}
          />
          <TextField
            size="small" label="From" type="date"
            value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
          <TextField
            size="small" label="To" type="date"
            value={dateTo} onChange={(e) => setDateTo(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={rows}
          columns={cols}
          autoHeight
          loading={loading}
          onRowClick={(p: GridRowParams) => navigate(`/builds/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
```

- [ ] **Step 2: Add AppLayout nav entry**

In `frontend/src/components/AppLayout.tsx`, locate `navItems`. Add (alphabetically — after `Bookings`, before `Change Requests`):

```typescript
import BuildIcon from '@mui/icons-material/Build';

// In navItems (insert alphabetically):
  { label: 'Builds', path: '/builds', icon: <BuildIcon /> },
```

If `BuildIcon` is already imported from a prior entry, reuse the import.

- [ ] **Step 3: Register the route**

In `frontend/src/App.tsx`, add below the existing release/environment routes:

```tsx
import BuildList from './pages/builds/BuildList';

// In <Routes>:
<Route path="/builds" element={<BuildList />} />
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/builds/BuildList.tsx frontend/src/components/AppLayout.tsx frontend/src/App.tsx
git commit -m "feat(phase-4-ui): BuildList page + top-level nav"
```

---

## Task 8: `BuildDetail` page

**Files:**
- Create: `frontend/src/pages/builds/BuildDetail.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/store/deploymentSlice.ts` — add a convenience thunk for per-build fetch

- [ ] **Step 1: Extend `deploymentSlice.ts` with a by-build thunk**

Open `frontend/src/store/deploymentSlice.ts`. After the existing `fetchDeployments` thunk, add:

```typescript
export const fetchDeploymentsByBuild = createAsyncThunk(
  'deployment/fetchByBuild',
  (buildId: number) => deploymentService.list({ build_id: buildId }),
);
```

And add a case to the reducer that stores results into a new field `state.byBuild: Record<number, Deployment[]>`. Update the state type:

```typescript
interface DeploymentState {
  items: Deployment[];
  byBuild: Record<number, Deployment[]>;
  current: Deployment | null;
  loading: boolean;
  error: string | null;
}
```

And the initial state:

```typescript
const initialState: DeploymentState = {
  items: [],
  byBuild: {},
  current: null,
  loading: false,
  error: null,
};
```

And the case:

```typescript
    b.addCase(fetchDeploymentsByBuild.fulfilled, (s, a) => {
      const buildId = a.meta.arg;
      s.byBuild[buildId] = a.payload;
    });
```

- [ ] **Step 2: Create `BuildDetail.tsx`**

```tsx
// frontend/src/pages/builds/BuildDetail.tsx
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box, Chip, CircularProgress, Divider, Paper, Stack, Typography,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchBuildById } from '../../store/buildSlice';
import { fetchDeploymentsByBuild } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { PipelineStep } from '../../types/build';
import type { DeploymentStatus } from '../../types/deployment';

function formatDuration(start: string | null, end: string | null): string {
  if (!start || !end) return '—';
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function PipelineStepRow({ step }: { step: PipelineStep }) {
  return (
    <Stack direction="row" spacing={2} alignItems="center" sx={{ py: 1 }}>
      <Chip size="small" label={step.status} />
      <Typography variant="body2" sx={{ flex: 1 }}>{step.name}</Typography>
      <Typography variant="caption" color="text.secondary">
        {formatDuration(step.started_at, step.finished_at)}
      </Typography>
    </Stack>
  );
}

export default function BuildDetail() {
  const { id } = useParams();
  const buildId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const build = useSelector((s: RootState) =>
    s.build.current?.id === buildId ? s.build.current : null,
  );
  const deployments = useSelector(
    (s: RootState) => s.deployment.byBuild[buildId] ?? [],
  );

  useEffect(() => {
    if (!Number.isNaN(buildId)) {
      dispatch(fetchBuildById(buildId));
      dispatch(fetchDeploymentsByBuild(buildId));
    }
  }, [dispatch, buildId]);

  if (!build) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5">Build {build.build_number ?? build.git_sha.slice(0, 8)}</Typography>
      <Stack direction="row" spacing={2} sx={{ mt: 1, color: 'text.secondary' }}>
        <Typography variant="body2">SubSystem #{build.subsystem_id}</Typography>
        <Typography variant="body2">Branch: {build.git_branch ?? '—'}</Typography>
        <Typography variant="body2">SHA: {build.git_sha.slice(0, 12)}</Typography>
        <Typography variant="body2">
          Committed {new Date(build.commit_timestamp).toLocaleString()}
        </Typography>
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Pipeline steps</Typography>
        <Divider sx={{ mb: 1 }} />
        {build.pipeline_steps.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No pipeline steps recorded.</Typography>
        ) : (
          build.pipeline_steps.map((step, i) => (
            <PipelineStepRow key={i} step={step} />
          ))
        )}
      </Paper>

      {build.jira_tickets.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Jira tickets</Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            {build.jira_tickets.map((t) => (
              <Chip key={t} label={t} size="small" />
            ))}
          </Stack>
        </Paper>
      )}

      {Object.keys(build.custom_fields).length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Custom fields</Typography>
          {Object.entries(build.custom_fields).map(([k, v]) => (
            <Stack key={k} direction="row" spacing={2} sx={{ py: 0.5 }}>
              <Typography variant="body2" sx={{ minWidth: 180 }} color="text.secondary">
                {k}
              </Typography>
              <Typography variant="body2">{String(v)}</Typography>
            </Stack>
          ))}
        </Paper>
      )}

      <Paper variant="outlined" sx={{ p: 2, mt: 3 }}>
        <Typography variant="h6" sx={{ mb: 1 }}>Deployments</Typography>
        <Divider sx={{ mb: 1 }} />
        {deployments.length === 0 ? (
          <Typography variant="body2" color="text.secondary">No deployments yet.</Typography>
        ) : (
          deployments.map((d) => (
            <Stack
              key={d.id}
              direction="row"
              spacing={2}
              alignItems="center"
              sx={{ py: 1, cursor: 'pointer', '&:hover': { bgcolor: 'action.hover' }, px: 1 }}
              onClick={() => navigate(`/deployments/${d.id}`)}
            >
              <Typography variant="body2" sx={{ flex: 1 }}>
                Env #{d.environment_id}
              </Typography>
              <DeploymentStatusChip status={d.status as DeploymentStatus} />
              <Typography variant="caption" color="text.secondary">
                {new Date(d.deployed_at).toLocaleString()}
              </Typography>
            </Stack>
          ))
        )}
      </Paper>
    </Box>
  );
}
```

- [ ] **Step 3: Add the route**

In `frontend/src/App.tsx`:

```tsx
import BuildDetail from './pages/builds/BuildDetail';

// In <Routes>:
<Route path="/builds/:id" element={<BuildDetail />} />
```

- [ ] **Step 4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/builds/BuildDetail.tsx frontend/src/store/deploymentSlice.ts frontend/src/App.tsx
git commit -m "feat(phase-4-ui): BuildDetail page with pipeline + linked deployments"
```

---

## Task 9: `DeploymentList` page + nav

**Files:**
- Create: `frontend/src/pages/deployments/DeploymentList.tsx`
- Modify: `frontend/src/components/AppLayout.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create `DeploymentList.tsx`**

```tsx
// frontend/src/pages/deployments/DeploymentList.tsx
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import {
  Box, MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeployments } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { DeploymentFilters, DeploymentStatus } from '../../types/deployment';

const STATUS_OPTIONS: DeploymentStatus[] = [
  'pending', 'in_progress', 'success', 'failed', 'rolled_back',
];

export default function DeploymentList() {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.deployment);

  const [environmentId, setEnvironmentId] = useState('');
  const [releaseId, setReleaseId] = useState('');
  const [status, setStatus] = useState<string>('');

  const filters = useMemo<DeploymentFilters>(() => {
    const f: DeploymentFilters = {};
    if (environmentId) f.environment_id = Number(environmentId);
    if (releaseId) f.release_id = Number(releaseId);
    if (status) f.status = status as DeploymentStatus;
    return f;
  }, [environmentId, releaseId, status]);

  useEffect(() => {
    dispatch(fetchDeployments(filters));
  }, [dispatch, filters]);

  const cols: GridColDef[] = [
    { field: 'environment_id', headerName: 'Env', width: 80 },
    { field: 'build_id', headerName: 'Build', width: 80 },
    {
      field: 'status', headerName: 'Status', width: 140,
      renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
    },
    { field: 'deployer_name', headerName: 'Deployer', flex: 1 },
    {
      field: 'deployed_at', headerName: 'Deployed at', width: 200,
      valueGetter: (v) => new Date(v as string).toLocaleString(),
    },
    { field: 'release_id', headerName: 'Release', width: 100 },
    { field: 'change_request_id', headerName: 'CR', width: 80 },
  ];

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 2 }}>Deployments</Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <TextField
            size="small" label="Environment id" type="number"
            value={environmentId} onChange={(e) => setEnvironmentId(e.target.value)}
            sx={{ width: 160 }}
          />
          <TextField
            size="small" label="Release id" type="number"
            value={releaseId} onChange={(e) => setReleaseId(e.target.value)}
            sx={{ width: 140 }}
          />
          <TextField
            select size="small" label="Status"
            value={status} onChange={(e) => setStatus(e.target.value)}
            sx={{ width: 160 }}
          >
            <MenuItem value="">Any</MenuItem>
            {STATUS_OPTIONS.map((s) => (
              <MenuItem key={s} value={s}>{s}</MenuItem>
            ))}
          </TextField>
        </Stack>
      </Paper>

      <Paper variant="outlined">
        <DataGrid
          rows={items}
          columns={cols}
          autoHeight
          loading={loading}
          onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
          disableRowSelectionOnClick
        />
      </Paper>
    </Box>
  );
}
```

- [ ] **Step 2: AppLayout nav entry**

In `frontend/src/components/AppLayout.tsx` `navItems`, add (alphabetical — after `Deployments`, before `Environments`):

```typescript
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';

  { label: 'Deployments', path: '/deployments', icon: <RocketLaunchIcon /> },
```

- [ ] **Step 3: Route**

In `frontend/src/App.tsx`:

```tsx
import DeploymentList from './pages/deployments/DeploymentList';

<Route path="/deployments" element={<DeploymentList />} />
```

- [ ] **Step 4: Typecheck + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/deployments/DeploymentList.tsx frontend/src/components/AppLayout.tsx frontend/src/App.tsx
git commit -m "feat(phase-4-ui): DeploymentList page + top-level nav"
```

---

## Task 10: `LinkChangeDialog` + `DeploymentDetail`

**Files:**
- Create: `frontend/src/components/deployments/LinkChangeDialog.tsx`
- Create: `frontend/src/pages/deployments/DeploymentDetail.tsx`
- Modify: `frontend/src/App.tsx`

### Step 1: `LinkChangeDialog.tsx`

Uses the existing `/api/v1/change-requests` endpoint. The endpoint returns a paginated list; we request a reasonable page size and let the user filter with a text field locally.

```tsx
// frontend/src/components/deployments/LinkChangeDialog.tsx
import { useEffect, useMemo, useState } from 'react';
import {
  Autocomplete, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  TextField,
} from '@mui/material';
import api from '../../services/api';

interface ChangeRequestOption {
  id: number;
  title: string;
  status: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (changeRequestId: number) => Promise<void>;
}

export default function LinkChangeDialog({ open, onClose, onSubmit }: Props) {
  const [options, setOptions] = useState<ChangeRequestOption[]>([]);
  const [value, setValue] = useState<ChangeRequestOption | null>(null);
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Fetch first 100 CRs; client-side filter via the Autocomplete.
    api.get<{ items: ChangeRequestOption[] } | ChangeRequestOption[]>(
      '/change-requests', { params: { limit: 100 } },
    )
      .then((r) => {
        const data = Array.isArray(r.data) ? r.data : r.data.items;
        setOptions(data);
      })
      .catch(() => setOptions([]));
  }, [open]);

  const filtered = useMemo(() => {
    if (!input.trim()) return options;
    const q = input.toLowerCase();
    return options.filter(
      (o) => o.title.toLowerCase().includes(q) || String(o.id).includes(q),
    );
  }, [options, input]);

  const handleSubmit = async () => {
    if (!value) return;
    setSubmitting(true);
    try {
      await onSubmit(value.id);
      setValue(null);
      setInput('');
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Link to a different change request</DialogTitle>
      <DialogContent>
        <Autocomplete
          sx={{ mt: 1 }}
          options={filtered}
          value={value}
          onChange={(_, v) => setValue(v)}
          inputValue={input}
          onInputChange={(_, v) => setInput(v)}
          getOptionLabel={(o) => `#${o.id} — ${o.title} (${o.status})`}
          renderInput={(params) => <TextField {...params} label="Search change requests" />}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={!value || submitting}>
          Link
        </Button>
      </DialogActions>
    </Dialog>
  );
}
```

### Step 2: `DeploymentDetail.tsx`

This page fetches the deployment, its build (via `fetchBuildById`), and the linked CR (direct API call — not enough state to justify a slice entry). Determines whether the link-change button is enabled by fetching the CR's lifecycle template name and checking for `"Code Deployment"`.

```tsx
// frontend/src/pages/deployments/DeploymentDetail.tsx
import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box, Button, Chip, CircularProgress, Divider, Paper, Stack,
  Tooltip, Typography,
} from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeploymentById, linkDeploymentChange } from '../../store/deploymentSlice';
import { fetchBuildById } from '../../store/buildSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import LinkChangeDialog from '../../components/deployments/LinkChangeDialog';
import { useSnackbar } from '../../hooks/useSnackbar';
import api from '../../services/api';

interface LinkedCr {
  id: number;
  title: string;
  status: string;
  lifecycle_id: number;
}

interface LifecycleTemplate {
  id: number;
  name: string;
}

export default function DeploymentDetail() {
  const { id } = useParams();
  const deploymentId = Number(id);
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const deployment = useSelector((s: RootState) =>
    s.deployment.current?.id === deploymentId ? s.deployment.current : null,
  );
  const build = useSelector((s: RootState) =>
    deployment && s.build.current?.id === deployment.build_id ? s.build.current : null,
  );

  const [cr, setCr] = useState<LinkedCr | null>(null);
  const [crLifecycle, setCrLifecycle] = useState<LifecycleTemplate | null>(null);
  const [linkOpen, setLinkOpen] = useState(false);

  useEffect(() => {
    if (!Number.isNaN(deploymentId)) dispatch(fetchDeploymentById(deploymentId));
  }, [dispatch, deploymentId]);

  useEffect(() => {
    if (deployment) dispatch(fetchBuildById(deployment.build_id));
  }, [dispatch, deployment]);

  useEffect(() => {
    if (!deployment) {
      setCr(null);
      setCrLifecycle(null);
      return;
    }
    api.get<LinkedCr>(`/change-requests/${deployment.change_request_id}`)
      .then((r) => {
        setCr(r.data);
        return api.get<LifecycleTemplate>(
          `/lifecycle-templates/${r.data.lifecycle_id}`,
        );
      })
      .then((r) => r && setCrLifecycle(r.data))
      .catch(() => {
        /* leave both null — button stays disabled */
      });
  }, [deployment]);

  if (!deployment || !build) {
    return (
      <Box sx={{ p: 3, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress />
      </Box>
    );
  }

  const isAutoCr = crLifecycle?.name === 'Code Deployment';
  const linkButton = (
    <Button
      variant="outlined"
      size="small"
      disabled={!isAutoCr}
      onClick={() => setLinkOpen(true)}
    >
      Link a different change request
    </Button>
  );

  const handleLink = async (newCrId: number) => {
    try {
      await dispatch(linkDeploymentChange({
        id: deploymentId,
        data: { change_request_id: newCrId },
      })).unwrap();
      snackbar.success('Change request relinked');
      // Refresh CR display
      const r = await api.get<LinkedCr>(`/change-requests/${newCrId}`);
      setCr(r.data);
      const tpl = await api.get<LifecycleTemplate>(
        `/lifecycle-templates/${r.data.lifecycle_id}`,
      );
      setCrLifecycle(tpl.data);
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to link change request');
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
        <Typography variant="h5">Deployment #{deployment.id}</Typography>
        <DeploymentStatusChip status={deployment.status} size="medium" />
      </Stack>
      <Stack direction="row" spacing={2} sx={{ color: 'text.secondary', mb: 3 }}>
        <Typography variant="body2">Env #{deployment.environment_id}</Typography>
        <Typography variant="body2">
          Deployed {new Date(deployment.deployed_at).toLocaleString()}
        </Typography>
        {deployment.deployer_name && (
          <Typography variant="body2">by {deployment.deployer_name}</Typography>
        )}
      </Stack>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">Build</Typography>
          <Button size="small" onClick={() => navigate(`/builds/${build.id}`)}>
            View full build
          </Button>
        </Stack>
        <Divider sx={{ mb: 1 }} />
        <Stack direction="row" spacing={3}>
          <Typography variant="body2">SubSystem #{build.subsystem_id}</Typography>
          <Typography variant="body2">SHA: {build.git_sha.slice(0, 12)}</Typography>
          <Typography variant="body2">Branch: {build.git_branch ?? '—'}</Typography>
          <Typography variant="body2">Build #{build.build_number ?? '—'}</Typography>
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">Change request</Typography>
          {isAutoCr
            ? linkButton
            : (
              <Tooltip title="This deployment is linked to a human-authored change request and cannot be relinked.">
                <span>{linkButton}</span>
              </Tooltip>
            )}
        </Stack>
        <Divider sx={{ mb: 1 }} />
        {cr ? (
          <Stack direction="row" spacing={2} alignItems="center">
            <Typography variant="body2" sx={{ flex: 1 }}>
              #{cr.id} — {cr.title}
            </Typography>
            <Chip size="small" label={cr.status} />
          </Stack>
        ) : (
          <Typography variant="body2" color="text.secondary">Loading…</Typography>
        )}
      </Paper>

      {Object.keys(deployment.custom_fields).length > 0 && (
        <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>Custom fields</Typography>
          {Object.entries(deployment.custom_fields).map(([k, v]) => (
            <Stack key={k} direction="row" spacing={2} sx={{ py: 0.5 }}>
              <Typography variant="body2" sx={{ minWidth: 180 }} color="text.secondary">
                {k}
              </Typography>
              <Typography variant="body2">{String(v)}</Typography>
            </Stack>
          ))}
        </Paper>
      )}

      <LinkChangeDialog
        open={linkOpen}
        onClose={() => setLinkOpen(false)}
        onSubmit={handleLink}
      />
    </Box>
  );
}
```

### Step 3: Add the route in `App.tsx`

```tsx
import DeploymentDetail from './pages/deployments/DeploymentDetail';

<Route path="/deployments/:id" element={<DeploymentDetail />} />
```

### Step 4: Typecheck + commit

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/deployments/LinkChangeDialog.tsx frontend/src/pages/deployments/DeploymentDetail.tsx frontend/src/App.tsx
git commit -m "feat(phase-4-ui): DeploymentDetail page + LinkChangeDialog"
```

---

## Task 11: Deployments tab on `EnvironmentDetail`

**Files:**
- Modify: `frontend/src/pages/environments/EnvironmentDetail.tsx`

- [ ] **Step 1: Read the existing tabs structure**

Open `frontend/src/pages/environments/EnvironmentDetail.tsx`. Note the pattern used for existing tabs (`Tab` components + render blocks keyed by a `tab` state value or similar). Add a new tab that matches the same pattern.

- [ ] **Step 2: Add a "Deployments" tab**

Add a new tab entry and its render block. The tab content is a scoped deployment list (filtered to this env).

```tsx
import { useEffect } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { DataGrid, GridColDef, GridRowParams } from '@mui/x-data-grid';
import { Paper } from '@mui/material';
import type { AppDispatch, RootState } from '../../store';
import { fetchDeployments } from '../../store/deploymentSlice';
import DeploymentStatusChip from '../../components/deployments/DeploymentStatusChip';
import type { DeploymentStatus } from '../../types/deployment';

function DeploymentsTabContent({ envId }: { envId: number }) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.deployment);

  useEffect(() => {
    dispatch(fetchDeployments({ environment_id: envId }));
  }, [dispatch, envId]);

  const rows = items.filter((d) => d.environment_id === envId);

  const cols: GridColDef[] = [
    { field: 'id', headerName: 'ID', width: 80 },
    { field: 'build_id', headerName: 'Build', width: 80 },
    {
      field: 'status', headerName: 'Status', width: 140,
      renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
    },
    { field: 'deployer_name', headerName: 'Deployer', flex: 1 },
    {
      field: 'deployed_at', headerName: 'Deployed at', width: 200,
      valueGetter: (v) => new Date(v as string).toLocaleString(),
    },
  ];

  return (
    <Paper variant="outlined">
      <DataGrid
        rows={rows}
        columns={cols}
        autoHeight
        loading={loading}
        onRowClick={(p: GridRowParams) => navigate(`/deployments/${p.id}`)}
        disableRowSelectionOnClick
      />
    </Paper>
  );
}
```

Place `DeploymentsTabContent` either inline inside `EnvironmentDetail.tsx` (if the file is small) or extract to `frontend/src/pages/environments/DeploymentsTab.tsx` (preferred if the file is already ~300 lines).

Then add a new `Tab` in the tabs row (label `Deployments`) and a new render block that calls `<DeploymentsTabContent envId={envId} />`.

Follow the exact tab-switching pattern used by the neighbouring tabs — do not introduce a new state mechanism.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/environments/
git commit -m "feat(phase-4-ui): Deployments tab on EnvironmentDetail"
```

---

## Task 12: Deployments tab on `ReleaseDetail`

**Files:**
- Modify: `frontend/src/pages/releases/ReleaseDetail.tsx`

- [ ] **Step 1: Mirror Task 11 for the release-scoped case**

Follow the same pattern as Task 11 but filter by `release_id`. Add a `DeploymentsTab` sibling under `frontend/src/pages/releases/project/` (if project-kind detail lives there) or inline inside `ReleaseDetail.tsx`. Open the file first to see the current tab structure and match it.

Content skeleton (put it in the right place, matching existing tab mechanics):

```tsx
function ReleaseDeploymentsTab({ releaseId }: { releaseId: number }) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const { items, loading } = useSelector((s: RootState) => s.deployment);

  useEffect(() => {
    dispatch(fetchDeployments({ release_id: releaseId }));
  }, [dispatch, releaseId]);

  const rows = items.filter((d) => d.release_id === releaseId);
  const cols: GridColDef[] = [
    { field: 'id', headerName: 'ID', width: 80 },
    { field: 'environment_id', headerName: 'Env', width: 80 },
    { field: 'build_id', headerName: 'Build', width: 80 },
    {
      field: 'status', headerName: 'Status', width: 140,
      renderCell: (p) => <DeploymentStatusChip status={p.value as DeploymentStatus} />,
    },
    {
      field: 'deployed_at', headerName: 'Deployed at', width: 200,
      valueGetter: (v) => new Date(v as string).toLocaleString(),
    },
  ];

  return (
    <Paper variant="outlined">
      <DataGrid
        rows={rows}
        columns={cols}
        autoHeight
        loading={loading}
        onRowClick={(p) => navigate(`/deployments/${p.id}`)}
        disableRowSelectionOnClick
      />
    </Paper>
  );
}
```

Required imports (same set as Task 11). Add a `Tab` labelled `Deployments` to the ReleaseDetail tabs row and a render block for it. Match the existing tab mechanics exactly.

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/releases/
git commit -m "feat(phase-4-ui): Deployments tab on ReleaseDetail"
```

---

## Task 13: `EnvironmentSchedule` renders deployments + backend helper tweak

**Files:**
- Modify: `backend/app/services/change_request_service.py` — `_get_deployments_for_schedule` returns `build_sha_short`
- Modify: `frontend/src/services/scheduleService.ts` — refine `deployments` type
- Modify: `frontend/src/pages/environments/EnvironmentSchedule.tsx`

### Step 1: Backend — include `build_sha_short` in schedule helper

In `backend/app/services/change_request_service.py`, locate `_get_deployments_for_schedule` (added in Phase 4 Sub-1 Task 18). Current shape returns minimal fields. Change it to also select the Build row and include `build_sha_short` + `build_sha` in each returned dict.

```python
async def _get_deployments_for_schedule(
    db, tenant_id: int, environment_id: int, date_from, date_to,
):
    from app.db.models.deployment import Deployment
    from app.db.models.build import Build
    from sqlalchemy import select
    q = (
        select(Deployment, Build)
        .join(Build, Build.id == Deployment.build_id)
        .where(
            Deployment.tenant_id == tenant_id,
            Deployment.environment_id == environment_id,
            Deployment.deleted_at.is_(None),
            Deployment.deployed_at >= date_from,
            Deployment.deployed_at <= date_to,
        ).order_by(Deployment.deployed_at)
    )
    rows = (await db.execute(q)).all()
    return [
        {
            "id": d.id,
            "build_id": d.build_id,
            "build_sha": b.git_sha,
            "build_sha_short": b.git_sha[:8],
            "release_id": d.release_id,
            "change_request_id": d.change_request_id,
            "status": d.status,
            "deployed_at": d.deployed_at.isoformat(),
            "deployer_name": d.deployer_name,
        }
        for d, b in rows
    ]
```

### Step 2: Test the backend change

The existing test `backend/tests/integration/test_environment_schedule_deployments.py` asserts `deployments` contains an id. Extend the assertion:

```python
    r = await client.get(...)
    body = r.json()
    dep = next(d for d in body["deployments"] if d["id"] == dep.id)
    assert dep["build_sha_short"] == "a" * 8
    assert dep["status"] == "success"
```

Find the `build` variable in that test (it creates one with `git_sha="a" * 40`). Replace the existing "any" assertion with the more specific one above.

Run the test:

```bash
cd backend && uv run pytest tests/integration/test_environment_schedule_deployments.py -v
```

Expected: still passes.

### Step 3: Update frontend type

In `frontend/src/services/scheduleService.ts`, change the `deployments: unknown[]` field to a proper type:

```typescript
export interface ScheduleDeployment {
  id: number;
  build_id: number;
  build_sha: string;
  build_sha_short: string;
  release_id: number | null;
  change_request_id: number;
  status: string;
  deployed_at: string;
  deployer_name: string | null;
}
```

And update the `EnvironmentScheduleResponse` type to use `deployments: ScheduleDeployment[]`.

### Step 4: Render deployments on the calendar

In `frontend/src/pages/environments/EnvironmentSchedule.tsx`:

- Add a new colour constant:

```typescript
const DEP_COLORS: Record<string, string> = {
  pending: '#607d8b',
  in_progress: '#607d8b',
  success: '#43a047',
  failed: '#e53935',
  rolled_back: '#ffb300',
};
```

- Add a `deploymentToEvent` function:

```typescript
import type { ScheduleDeployment } from '../../services/scheduleService';

function deploymentToEvent(d: ScheduleDeployment): EventInput {
  const color = DEP_COLORS[d.status] ?? '#607d8b';
  return {
    id: `deployment-${d.id}`,
    title: `Deploy ${d.build_sha_short} (${d.status})`,
    start: d.deployed_at,
    end: d.deployed_at,
    backgroundColor: color,
    borderColor: color,
    extendedProps: { kind: 'deployment', deployment: d },
  };
}
```

- Extend the `EventExtProps` union:

```typescript
type EventExtProps =
  | { kind: 'booking'; booking: ScheduleBooking }
  | { kind: 'cr'; changeRequest: ScheduleChangeRequest }
  | { kind: 'deployment'; deployment: ScheduleDeployment };
```

- Extend the `events` array:

```typescript
const events: EventInput[] = [
  ...(data?.bookings ?? []).map(bookingToEvent),
  ...(data?.change_requests ?? []).map(crToEvent),
  ...(data?.deployments ?? []).map(deploymentToEvent),
];
```

- Extend `handleEventClick`:

```typescript
  const handleEventClick = (arg: EventClickArg) => {
    const ext = arg.event.extendedProps as EventExtProps;
    if (ext.kind === 'booking') {
      navigate(`/bookings/${ext.booking.id}`);
    } else if (ext.kind === 'cr') {
      navigate(`/change-requests/${ext.changeRequest.id}`);
    } else {
      navigate(`/deployments/${ext.deployment.id}`);
    }
  };
```

- Extend the legend — add three chips (Deployment success / failed / in-progress, using the DEP_COLORS values) after the existing CR chips.

### Step 5: Typecheck

```bash
cd frontend && npx tsc --noEmit
```

### Step 6: Commit

```bash
git add backend/app/services/change_request_service.py backend/tests/integration/test_environment_schedule_deployments.py frontend/src/services/scheduleService.ts frontend/src/pages/environments/EnvironmentSchedule.tsx
git commit -m "feat(phase-4-ui): render deployments on EnvironmentSchedule; schedule helper returns build_sha"
```

---

## Task 14: Admin entity-config routes for Build + Deployment custom fields

**Files:**
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/App.tsx`

### Step 1: Confirm existing generic pattern

The existing nav items at `/admin/config/<entity>` point to a generic `CustomFieldDefinitionsPanel` component. Grep:

```bash
grep -rn "admin/config" frontend/src/App.tsx
```

Identify the route that mounts the generic config page. It likely takes an `entity_type` param from the URL path.

### Step 2: Add nav entries

In `AdminLayout.tsx`, in the `entityNavItems` array, add two new entries:

```typescript
  { label: 'Builds', path: '/admin/config/build', icon: <BuildIcon fontSize="small" /> },
  { label: 'Deployments', path: '/admin/config/deployment', icon: <BuildIcon fontSize="small" /> },
```

### Step 3: Verify routes work

The existing `/admin/config/:entity` route (or similar) should pick these up automatically since the backend already accepts `build` + `deployment` as entity types (Sub-1 Task 5). If the route is NOT parameterised and instead has per-entity components, add two routes in `App.tsx` following the existing pattern.

### Step 4: Typecheck + commit

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/pages/admin/AdminLayout.tsx frontend/src/App.tsx
git commit -m "feat(phase-4-ui): admin config routes for Build + Deployment custom fields"
```

---

## Task 15: Cross-tenant integration test

**Files:**
- Create: `backend/tests/integration/test_phase4_tenant_isolation.py`

- [ ] **Step 1: Write the test**

```python
"""Cross-tenant isolation for Phase 4 resources (api_keys, builds, deployments)."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.services import api_key_service, change_request_service


async def _seed_one_tenant(db_session, tenant, user, name_prefix: str):
    """Create an api_key, build, deployment in a single tenant."""
    from app.db.models.system import System, SubSystem
    from app.db.models.environment import Environment
    from app.db.models.build import Build
    from app.db.models.deployment import Deployment

    await change_request_service.seed_default_lifecycles(db_session, tenant.id)

    sys_ = System(tenant_id=tenant.id, name=f"{name_prefix}-Orders")
    db_session.add(sys_)
    await db_session.flush()
    sub = SubSystem(tenant_id=tenant.id, system_id=sys_.id, name=f"{name_prefix}-api")
    env = Environment(tenant_id=tenant.id, name=f"{name_prefix}-sit", environment_type="integration")
    db_session.add_all([sub, env])
    await db_session.flush()

    key, _raw = await api_key_service.create_key(
        db_session, tenant_id=tenant.id, created_by=user.id,
        name=f"{name_prefix}-key", scopes=["webhooks:deployment"],
    )

    build = Build(
        tenant_id=tenant.id, subsystem_id=sub.id,
        git_sha=f"{name_prefix}sha" + "0" * 30,
        build_number="#1",
        commit_timestamp=datetime(2026, 4, 22, tzinfo=timezone.utc),
    )
    db_session.add(build)
    await db_session.flush()
    cr = await change_request_service.create_code_deployment(
        db_session, tenant_id=tenant.id, raised_by=user.id,
        title=f"{name_prefix} CR", description="x",
    )
    dep = Deployment(
        tenant_id=tenant.id, build_id=build.id, environment_id=env.id,
        change_request_id=cr.id, event_id=str(uuid4()),
        deployed_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
        status="success",
    )
    db_session.add(dep)
    await db_session.commit()
    return {"api_key": key, "build": build, "deployment": dep, "cr": cr}


@pytest.mark.asyncio
async def test_tenant_a_cannot_see_tenant_b_resources(
    client, auth_headers, db_session, test_tenant, test_user,
    second_tenant_factory,  # plan assumption: there's a factory for a second tenant
):
    # test_tenant / test_user = tenant A; auth_headers authenticates as user in tenant A.
    a = await _seed_one_tenant(db_session, test_tenant, test_user, "A")

    # Seed a tenant B with its own admin + resources (no API session for B — we
    # just check tenant A's JWT cannot see them).
    other_tenant, other_user = await second_tenant_factory()
    b = await _seed_one_tenant(db_session, other_tenant, other_user, "B")

    # Tenant A list endpoints must not contain tenant B's resources.
    r = await client.get("/api/v1/api-keys", headers=auth_headers)
    assert r.status_code == 200
    ids = {k["id"] for k in r.json()}
    assert a["api_key"].id in ids
    assert b["api_key"].id not in ids

    r = await client.get("/api/v1/builds", headers=auth_headers)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert a["build"].id in ids
    assert b["build"].id not in ids

    r = await client.get("/api/v1/deployments", headers=auth_headers)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()}
    assert a["deployment"].id in ids
    assert b["deployment"].id not in ids

    # Direct detail fetches for tenant B ids return 404 under tenant A JWT.
    r = await client.get(f"/api/v1/builds/{b['build'].id}", headers=auth_headers)
    assert r.status_code == 404
    r = await client.get(f"/api/v1/deployments/{b['deployment'].id}", headers=auth_headers)
    assert r.status_code == 404

    # Link-change attempting to cross tenants → 400 (target CR not found).
    r = await client.post(
        f"/api/v1/deployments/{a['deployment'].id}/link-change",
        headers=auth_headers,
        json={"change_request_id": b["cr"].id},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Check if `second_tenant_factory` fixture exists; if not, add it**

Grep:

```bash
grep -rn "second_tenant_factory\|other_tenant" backend/tests/conftest.py
```

If absent, add this fixture to `backend/tests/conftest.py`:

```python
@pytest_asyncio.fixture
async def second_tenant_factory(db_session):
    """Yields an async factory that creates a second tenant with its own admin."""
    async def _factory(name: str = "Second Org", slug: str = "second-org"):
        from app.db.models.tenant import Tenant
        from app.db.models.user import User
        from app.core.security import get_password_hash
        t = Tenant(name=name, slug=slug)
        db_session.add(t)
        await db_session.commit()
        await db_session.refresh(t)
        u = User(
            tenant_id=t.id, username=f"{slug}-admin", email=f"admin@{slug}.com",
            password_hash=get_password_hash("password123"), role="Admin", is_active=True,
        )
        db_session.add(u)
        await db_session.commit()
        await db_session.refresh(u)
        return t, u
    return _factory
```

- [ ] **Step 3: Run the test**

```bash
cd backend && uv run pytest tests/integration/test_phase4_tenant_isolation.py -v
```

Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_phase4_tenant_isolation.py backend/tests/conftest.py
git commit -m "test(phase-4): cross-tenant isolation for api_keys + builds + deployments"
```

---

## Task 16: Final verification

- [ ] **Step 1: Full backend suite**

```bash
cd backend && uv run pytest -q 2>&1 | tail -5
```

Expected: 600 + new Phase 4 Sub-2 tests pass (cross-tenant adds 1, schedule extension still passes).

- [ ] **Step 2: Frontend typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Frontend tests**

```bash
cd frontend && npx vitest run src/components/ 2>&1 | tail -10
```

Expected: all new component tests pass (DeploymentStatusChip, ApiKeyCreatedDialog).

- [ ] **Step 4: Manual smoke (against the live dev stack)**

If the dev stack is still running:

1. Log in as admin on the `demo` tenant.
2. Visit `/tenant/api-keys` — page loads; click **New key** → fill form → submit → raw key appears in a dialog.
3. Copy the raw key. `curl -X POST http://localhost:8000/api/v1/webhooks/deployment -H "X-Api-Key: $RAW" -H "Content-Type: application/json" -d @/tmp/dep.json` with a minimal body that matches a seeded system/subsystem/env. Response 200.
4. Visit `/builds` — new row visible. Click through → BuildDetail shows pipeline + linked deployment.
5. Visit `/deployments` — new row visible. Click through → DeploymentDetail shows build + CR.
6. Open EnvironmentDetail for the env you deployed to → Deployments tab shows the new row.
7. Open EnvironmentSchedule → the deployment appears as a green event on its deployed_at date.

Record any UI glitch as a follow-up. No extra commits unless a bug turns up.

- [ ] **Step 5: Mark spec implemented**

Edit `docs/superpowers/specs/2026-04-24-phase-4-sub2-frontend-design.md`:

```markdown
**Status:** Implemented on `feature/phase-4-sub2-frontend` — awaiting MR merge
```

- [ ] **Step 6: Commit the status flip**

```bash
git add docs/superpowers/specs/2026-04-24-phase-4-sub2-frontend-design.md
git commit -m "docs(spec): mark Phase 4 Sub-2 spec as implemented"
```
