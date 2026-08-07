/**
 * ReleaseForm — create / edit a release.
 *
 * Type (which implies the lifecycle) + Kind are rendered at create time
 * as plain selects. Everything else (standard fields + custom fields) is
 * rendered via LifecycleAwareFieldsPanel so visibility + editability honour
 * the lifecycle's field_permissions for the current state and the caller's
 * role.
 */
import { useEffect, useMemo, useState } from 'react';
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
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { AppDispatch, RootState } from '../../store';
import {
  fetchLifecycleTemplates,
  selectTemplatesForEntity,
} from '../../store/bookingLifecycleSlice';
import { fetchDefinitions } from '../../store/customFieldSlice';
import { createRelease, updateRelease, fetchRelease } from '../../store/releaseSlice';
import { useAllProjects } from '../../hooks/useAllProjects';
import { useSnackbar } from '../../hooks/useSnackbar';
import LifecycleAwareFieldsPanel, {
  type FieldPermissionsMap,
} from '../../components/lifecycle/LifecycleAwareFieldsPanel';
import { toIsoDatetime } from '../../utils/dates';
import type {
  ReleaseResponse,
  ReleaseCreatePayload,
  ReleaseUpdatePayload,
} from '../../types/release';

// Fields we render explicitly at create time (Type + Kind). These are excluded
// from the lifecycle-aware panel even if the lifecycle lists them as standard
// fields, to avoid duplicate controls.
const FIELDS_HANDLED_SEPARATELY = new Set(['release_type', 'release_kind']);

interface ReleaseFormProps {
  open: boolean;
  onClose: () => void;
  /** When provided, the form acts as an edit dialog rather than create. */
  release?: ReleaseResponse | null;
}

function initialStandardValues(release?: ReleaseResponse | null): Record<string, unknown> {
  return {
    name: release?.name ?? '',
    description: release?.description ?? '',
    release_type: release?.release_type ?? '',
    target_date: release?.target_date
      ? new Date(release.target_date).toISOString().slice(0, 10)
      : '',
    actual_date: release?.actual_date
      ? new Date(release.actual_date).toISOString().slice(0, 10)
      : '',
    scope_deadline: release?.scope_deadline
      ? new Date(release.scope_deadline).toISOString().slice(0, 10)
      : '',
  };
}

function extractErrorMessage(err: unknown, fallback: string): string {
  const axiosErr = err as { response?: { data?: { detail?: unknown } } };
  const detail = axiosErr?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail[0]?.msg) {
    const first = detail[0] as { loc?: unknown[]; msg: string };
    const loc = Array.isArray(first.loc) ? first.loc.join('.') : 'field';
    return `${loc}: ${first.msg}`;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export default function ReleaseForm({ open, onClose, release }: ReleaseFormProps) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();
  const isEdit = !!release;

  const templates = useSelector(selectTemplatesForEntity('release'));
  const user = useSelector((s: RootState) => s.auth.user);
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['release'] ?? []
  );
  // Not the shared `project` slice: ReleaseList's own Project filter reads
  // it too, and would race this dialog's fetch over the same slice.
  const { projects, truncated: projectsTruncated } = useAllProjects();

  const [kind, setKind] = useState<'project' | 'enterprise'>(
    (release?.release_kind as 'project' | 'enterprise') ?? 'project'
  );
  // The Owning project, distinct from `kind` above (release_kind='project'
  // means "not enterprise" — an unrelated toggle). Kept as its own piece of
  // state, deliberately rendered away from the Kind/Type block so the two
  // are never visually confused.
  const [owningProjectId, setOwningProjectId] = useState<number | null>(
    release?.owning_project_id ?? null
  );
  const [lifecycleTemplateId, setLifecycleTemplateId] = useState<number | null>(
    release?.lifecycle_template_id ?? null
  );
  const [standardValues, setStandardValues] = useState<Record<string, unknown>>(
    initialStandardValues(release)
  );
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>(
    (release?.custom_fields ?? {}) as Record<string, unknown>
  );

  // Fetch required metadata when the dialog opens. Projects are not fetched
  // here — useAllProjects above already narrows to active ones and fetches
  // on mount, the same shape as ReleaseList's own Project filter; a release
  // that already holds an archived project keeps it selectable via the
  // archived-value MenuItem below, the same shape as EnvironmentDetail's
  // Owner/Operations Group selects.
  useEffect(() => {
    if (open) {
      dispatch(fetchLifecycleTemplates('release'));
      dispatch(fetchDefinitions('release'));
    }
  }, [dispatch, open]);

  // Sync local state with the release prop whenever the dialog (re)opens
  useEffect(() => {
    if (open) {
      setStandardValues(initialStandardValues(release));
      setCustomFieldValues((release?.custom_fields ?? {}) as Record<string, unknown>);
      setLifecycleTemplateId(release?.lifecycle_template_id ?? null);
      setKind((release?.release_kind as 'project' | 'enterprise') ?? 'project');
      setOwningProjectId(release?.owning_project_id ?? null);
    }
  }, [open, release]);

  // Templates that match the currently selected kind (null applies_to_kind = any kind)
  const filteredTemplates = useMemo(
    () => templates.filter((t) => t.applies_to_kind === kind || t.applies_to_kind == null),
    [templates, kind]
  );

  // Auto-select the tenant default on create (using kind-filtered list)
  useEffect(() => {
    if (!isEdit && open && filteredTemplates.length > 0 && lifecycleTemplateId === null) {
      const defaultTpl = filteredTemplates.find((t) => t.is_default) ?? filteredTemplates[0];
      setLifecycleTemplateId(defaultTpl.id);
      setStandardValues((v) => ({ ...v, release_type: defaultTpl.name }));
    }
  }, [isEdit, open, filteredTemplates, lifecycleTemplateId]);

  // When kind changes and the selected template no longer applies, reset to default for new kind
  useEffect(() => {
    if (!isEdit && lifecycleTemplateId !== null) {
      const currentTplStillValid = filteredTemplates.some((t) => t.id === lifecycleTemplateId);
      if (!currentTplStillValid) {
        const defaultTpl = filteredTemplates.find((t) => t.is_default) ?? filteredTemplates[0] ?? null;
        setLifecycleTemplateId(defaultTpl?.id ?? null);
        setStandardValues((v) => ({ ...v, release_type: defaultTpl?.name ?? '' }));
      }
    }
  }, [isEdit, kind, filteredTemplates, lifecycleTemplateId]);

  // Bound lifecycle template (fetched into the bookingLifecycle slice by fetchLifecycleTemplates)
  const lifecycleTpl = useMemo(
    () => templates.find((t) => t.id === lifecycleTemplateId) ?? null,
    [templates, lifecycleTemplateId]
  );

  const currentState = release?.status ?? 'draft';
  const userRole = user?.role ?? 'Viewer';

  // Strip fields that we render explicitly (release_type, release_kind).
  const fieldPermissionsForPanel = useMemo<Record<string, FieldPermissionsMap>>(() => {
    const raw = (lifecycleTpl?.definition?.field_permissions ?? {}) as Record<
      string,
      FieldPermissionsMap
    >;
    const out: Record<string, FieldPermissionsMap> = {};
    for (const [state, perm] of Object.entries(raw)) {
      const stdClone = { ...(perm.standard_fields ?? {}) };
      for (const k of FIELDS_HANDLED_SEPARATELY) delete stdClone[k];
      out[state] = { ...perm, standard_fields: stdClone };
    }
    return out;
  }, [lifecycleTpl]);

  // Filter custom field definitions to those the current state actually references,
  // AND whose entity_subtype matches this release's type (null subtype = all types).
  // Hidden fields never render (matches booking behaviour).
  const visibleCustomFieldDefs = useMemo(() => {
    const customPerms =
      fieldPermissionsForPanel[currentState]?.custom_fields ?? {};
    const releaseType = standardValues.release_type as string | undefined;
    return customFieldDefs.filter(
      (d) =>
        d.field_key in customPerms &&
        (d.entity_subtype === null ||
          d.entity_subtype === undefined ||
          d.entity_subtype === releaseType)
    );
  }, [customFieldDefs, fieldPermissionsForPanel, currentState, standardValues.release_type]);

  const handleClose = () => {
    onClose();
  };

  const validateBeforeSubmit = (): string | null => {
    const name = typeof standardValues.name === 'string' ? standardValues.name.trim() : '';
    if (!name) return 'Name is required';
    if (!isEdit) {
      if (!lifecycleTemplateId) return 'Type is required';
    }
    return null;
  };

  const handleSubmit = async () => {
    const validationError = validateBeforeSubmit();
    if (validationError) {
      snackbar.error(validationError);
      return;
    }

    try {
      if (isEdit && release) {
        const payload: ReleaseUpdatePayload = {
          name: standardValues.name as string,
          description: (standardValues.description as string) || null,
          target_date: toIsoDatetime(standardValues.target_date),
          actual_date: toIsoDatetime(standardValues.actual_date),
          scope_deadline:
            kind === 'project' ? toIsoDatetime(standardValues.scope_deadline) : undefined,
          // Sent unconditionally, like every other field in this fixed-shape
          // payload — including when unchanged. The backend's carve-out
          // (release_service.py) tolerates resubmitting the release's own
          // already-archived project id; it only re-validates when the value
          // actually changes.
          owning_project_id: owningProjectId,
          custom_fields: customFieldValues,
        };
        await dispatch(updateRelease({ id: release.id, data: payload })).unwrap();
        dispatch(fetchRelease(release.id));
        snackbar.success('Release updated');
        handleClose();
      } else {
        const selectedTpl = templates.find((t) => t.id === lifecycleTemplateId);
        const payload: ReleaseCreatePayload = {
          name: standardValues.name as string,
          description: (standardValues.description as string) || null,
          release_type: selectedTpl?.name ?? (standardValues.release_type as string) ?? '',
          release_kind: kind,
          owning_project_id: owningProjectId,
          lifecycle_template_id: lifecycleTemplateId ?? undefined,
          target_date: toIsoDatetime(standardValues.target_date),
          scope_deadline:
            kind === 'project' ? toIsoDatetime(standardValues.scope_deadline) : undefined,
          custom_fields:
            Object.keys(customFieldValues).length > 0 ? customFieldValues : undefined,
        };
        const result = await dispatch(createRelease(payload)).unwrap();
        snackbar.success('Release created');
        handleClose();
        navigate(`/releases/${result.id}`);
      }
    } catch (err) {
      snackbar.error(extractErrorMessage(err, 'Failed to save release'));
    }
  };

  const panelHasAnyFields =
    Object.keys(fieldPermissionsForPanel[currentState]?.standard_fields ?? {}).length > 0 ||
    visibleCustomFieldDefs.length > 0;

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Release' : 'New Release'}</DialogTitle>
      <DialogContent>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
          {/* Type + Kind: selectable at create time, read-only chips on edit */}
          {!isEdit ? (
            <>
              <TextField
                select
                label="Kind"
                fullWidth
                value={kind}
                onChange={(e) => setKind(e.target.value as 'project' | 'enterprise')}
                helperText="Project releases belong to a single team. Enterprise releases roll up multiple project releases."
              >
                <MenuItem value="project">Project</MenuItem>
                <MenuItem value="enterprise">Enterprise</MenuItem>
              </TextField>

              <TextField
                select
                label="Type"
                required
                fullWidth
                value={lifecycleTemplateId ?? ''}
                onChange={(e) => {
                  const id = e.target.value === '' ? null : Number(e.target.value);
                  setLifecycleTemplateId(id);
                  const tpl = filteredTemplates.find((t) => t.id === id);
                  if (tpl) {
                    setStandardValues((v) => ({ ...v, release_type: tpl.name }));
                  }
                }}
                helperText="Type determines the release lifecycle. Manage types in Admin → Releases → Lifecycle."
              >
                {filteredTemplates.map((t) => (
                  <MenuItem key={t.id} value={t.id}>
                    {t.name}
                    {t.is_default ? ' (default)' : ''}
                  </MenuItem>
                ))}
              </TextField>
            </>
          ) : (
            <Stack direction="row" spacing={1}>
              <Chip label={`Type: ${release?.release_type ?? ''}`} />
              <Chip label={`Kind: ${release?.release_kind ?? 'project'}`} />
              <Chip label={`State: ${currentState}`} color="primary" size="small" />
            </Stack>
          )}

          {kind === 'project' && (
            <TextField
              label="Scope deadline"
              type="date"
              fullWidth
              value={(standardValues.scope_deadline as string) ?? ''}
              onChange={(e) =>
                setStandardValues((v) => ({ ...v, scope_deadline: e.target.value }))
              }
              InputLabelProps={{ shrink: true }}
              helperText="Baseline for scope creep. Setting this adds a Scope Sign-off gate for the Release Manager."
            />
          )}

          {/* Owning project (optional) — deliberately away from the Kind/Type
              block above so it is never confused with release_kind='project'
              (which means "not enterprise", an unrelated toggle). */}
          <TextField
            select
            label="Owning project"
            fullWidth
            value={owningProjectId ?? ''}
            onChange={(e) =>
              setOwningProjectId(e.target.value === '' ? null : Number(e.target.value))
            }
            helperText={
              projectsTruncated
                ? `Only the first ${projects.length} projects are shown.`
                : 'Optional — which project this release belongs to.'
            }
          >
            <MenuItem value="">No project</MenuItem>
            {/* An archived project stays selectable only when it is the one
                already on this release, so opening this form after its
                project was archived doesn't blank a valid value — same shape
                as EnvironmentDetail's Owner/Operations Group selects. The
                backend still returns owning_project_name for an archived
                project, so the label is available even though
                useAllProjects (is_active: true) no longer lists it. */}
            {release &&
              release.owning_project_id != null &&
              owningProjectId === release.owning_project_id &&
              !projects.some((p) => p.id === owningProjectId) && (
                <MenuItem value={owningProjectId}>
                  {release.owning_project_name ?? `#${owningProjectId}`} (archived)
                </MenuItem>
              )}
            {projects.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                {p.name}
              </MenuItem>
            ))}
          </TextField>

          {/* Lifecycle-driven fields */}
          {panelHasAnyFields ? (
            <LifecycleAwareFieldsPanel
              entityType="release"
              entitySubtype={standardValues.release_type as string}
              currentState={currentState}
              userRole={userRole}
              fieldPermissions={fieldPermissionsForPanel}
              standardValues={standardValues}
              customFieldDefinitions={visibleCustomFieldDefs}
              customFieldValues={customFieldValues}
              onStandardChange={(key, value) =>
                setStandardValues((v) => ({ ...v, [key]: value }))
              }
              onCustomChange={(key, value) =>
                setCustomFieldValues((v) => ({ ...v, [key]: value }))
              }
            />
          ) : (
            <Typography variant="body2" color="text.secondary">
              The selected lifecycle has no editable fields configured for state
              &ldquo;{currentState}&rdquo;. Configure field permissions in Admin →
              Releases → Lifecycle, or edit the release in a state that grants
              edit permissions to your role.
            </Typography>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose}>Cancel</Button>
        <Button onClick={handleSubmit} variant="contained">
          {isEdit ? 'Save' : 'Create Release'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
