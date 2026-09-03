/**
 * IncidentForm — create / edit an incident.
 *
 * Create: /incidents/new
 * Edit:   /incidents/:id/edit
 *
 * Uses the same LifecycleAwareFieldsPanel pattern as ReleaseForm for custom
 * fields, and MUI Autocomplete searchable pickers for environment, deployment,
 * causal release, fix release, system, and subsystem.
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Paper,
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
import { fetchIncident, createIncident, updateIncident } from '../../store/incidentSlice';
import { useSnackbar } from '../../hooks/useSnackbar';
import LifecycleAwareFieldsPanel, {
  type FieldPermissionsMap,
} from '../../components/lifecycle/LifecycleAwareFieldsPanel';
import { SEVERITIES } from '../../utils/incidentSeverity';
import { environmentService } from '../../services/environmentService';
import { deploymentService } from '../../services/deploymentService';
import { releaseService } from '../../services/releaseService';
import { systemService } from '../../services/systemService';
import { useAllSystems } from '../../hooks/useAllSystems';
import type { EnvironmentResponse } from '../../types/environment';
import type { Deployment } from '../../types/deployment';
import type { ReleaseListItemResponse } from '../../types/release';
import type { SubSystemResponse } from '../../types/system';
import type { IncidentCreate, IncidentUpdate } from '../../types/incident';
import PageHeader from '../../components/layout/PageHeader';

// ─── helper ────────────────────────────────────────────────────────────────
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

// ─── component ─────────────────────────────────────────────────────────────
export default function IncidentForm() {
  const { id } = useParams<{ id?: string }>();
  const isEdit = !!id;
  const incidentId = id ? Number(id) : null;

  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const user = useSelector((s: RootState) => s.auth.user);
  const detail = useSelector((s: RootState) => s.incident.detail);
  const templates = useSelector(selectTemplatesForEntity('incident'));
  const customFieldDefs = useSelector(
    (s: RootState) => s.customField.definitions['incident'] ?? [],
  );

  // ── form fields ──────────────────────────────────────────────────────────
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [severity, setSeverity] = useState<string>('P3');
  const [source, setSource] = useState('manual');
  const [externalRef, setExternalRef] = useState('');
  const [detectedAt, setDetectedAt] = useState('');

  // picker selections (IDs)
  const [envId, setEnvId] = useState<number | null>(null);
  const [deploymentId, setDeploymentId] = useState<number | null>(null);
  const [releaseId, setReleaseId] = useState<number | null>(null);       // causal
  const [fixReleaseId, setFixReleaseId] = useState<number | null>(null); // fix
  const [systemId, setSystemId] = useState<number | null>(null);
  const [subsystemId, setSubsystemId] = useState<number | null>(null);

  // custom fields (for lifecycle-aware panel)
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});

  // ── picker option lists ───────────────────────────────────────────────────
  const [environments, setEnvironments] = useState<EnvironmentResponse[]>([]);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [releases, setReleases] = useState<ReleaseListItemResponse[]>([]);
  // Not the shared systems slice: since the C3 conversion (a later task) it
  // will become SystemCatalog's current filtered page, so this picker would
  // silently offer a subset.
  const { systems, truncated: systemsTruncated } = useAllSystems();
  const [subsystems, setSubsystems] = useState<SubSystemResponse[]>([]);

  // loading state for initial fetch on edit
  const [loadingEdit, setLoadingEdit] = useState(isEdit);

  // ── boot: fetch metadata + edit data ─────────────────────────────────────
  useEffect(() => {
    dispatch(fetchLifecycleTemplates('incident'));
    dispatch(fetchDefinitions('incident'));
    environmentService
      .listEnvironments()
      .then((paged) => setEnvironments(paged.rows))
      .catch(() => setEnvironments([]));
    deploymentService.list().then((paged) => setDeployments(paged.rows)).catch(() => setDeployments([]));
    // Explicit limit: the server default is 50, which silently omits releases
    // from a picker with no indication any are missing.
    releaseService.list({ limit: 200 }).then((paged) => setReleases(paged.rows)).catch(() => setReleases([]));
  }, [dispatch]);

  // fetch subsystems when system changes
  useEffect(() => {
    if (systemId == null) {
      setSubsystems([]);
      setSubsystemId(null);
      return;
    }
    systemService
      .listSubSystems(systemId)
      .then(setSubsystems)
      .catch(() => setSubsystems([]));
    setSubsystemId(null);
  }, [systemId]);

  // on edit: load incident then pre-fill
  useEffect(() => {
    if (!isEdit || incidentId == null) return;
    dispatch(fetchIncident(incidentId));
  }, [isEdit, incidentId, dispatch]);

  useEffect(() => {
    if (!isEdit || !detail || detail.id !== incidentId) return;
    setTitle(detail.title);
    setDescription(detail.description ?? '');
    setSeverity(detail.severity);
    setSource(detail.source);
    setExternalRef(detail.external_ref ?? '');
    setDetectedAt(
      detail.detected_at ? new Date(detail.detected_at).toISOString().slice(0, 10) : '',
    );
    setEnvId(detail.environment_id);
    setDeploymentId(detail.deployment_id);
    setReleaseId(detail.release_id);
    setFixReleaseId(detail.fix_release_id);
    setSystemId(detail.system_id);
    setSubsystemId(detail.subsystem_id);
    setCustomFieldValues((detail.custom_fields ?? {}) as Record<string, unknown>);
    setLoadingEdit(false);
  }, [isEdit, detail, incidentId]);

  // ── lifecycle template + field permissions ────────────────────────────────
  const currentStatus = isEdit ? (detail?.status ?? 'new') : 'new';
  const userRole = user?.role ?? 'Viewer';

  const lifecycleTpl = useMemo(
    () => templates.find((t) => t.is_default) ?? templates[0] ?? null,
    [templates],
  );

  const fieldPermissionsForPanel = useMemo<Record<string, FieldPermissionsMap>>(() => {
    return (lifecycleTpl?.definition?.field_permissions ?? {}) as Record<
      string,
      FieldPermissionsMap
    >;
  }, [lifecycleTpl]);

  const visibleCustomFieldDefs = useMemo(() => {
    const customPerms = fieldPermissionsForPanel[currentStatus]?.custom_fields ?? {};
    return customFieldDefs.filter(
      (d) => d.field_key in customPerms,
    );
  }, [customFieldDefs, fieldPermissionsForPanel, currentStatus]);

  const panelHasAnyFields =
    Object.keys(fieldPermissionsForPanel[currentStatus]?.standard_fields ?? {}).length > 0 ||
    visibleCustomFieldDefs.length > 0;

  // ── derived picker values ─────────────────────────────────────────────────
  const selectedEnv = useMemo(
    () => environments.find((e) => e.id === envId) ?? null,
    [environments, envId],
  );
  const selectedDeployment = useMemo(
    () => deployments.find((d) => d.id === deploymentId) ?? null,
    [deployments, deploymentId],
  );
  const selectedRelease = useMemo(
    () => releases.find((r) => r.id === releaseId) ?? null,
    [releases, releaseId],
  );
  const selectedFixRelease = useMemo(
    () => releases.find((r) => r.id === fixReleaseId) ?? null,
    [releases, fixReleaseId],
  );
  const selectedSystem = useMemo(
    () => systems.find((s) => s.id === systemId) ?? null,
    [systems, systemId],
  );
  const selectedSubsystem = useMemo(
    () => subsystems.find((s) => s.id === subsystemId) ?? null,
    [subsystems, subsystemId],
  );

  // ── submit ────────────────────────────────────────────────────────────────
  const handleSubmit = async () => {
    if (!title.trim()) {
      snackbar.error('Title is required');
      return;
    }
    if (!severity) {
      snackbar.error('Severity is required');
      return;
    }

    try {
      if (isEdit && incidentId != null) {
        const payload: IncidentUpdate = {
          title: title.trim(),
          description: description.trim() || undefined,
          severity: severity as IncidentUpdate['severity'],
          environment_id: envId,
          deployment_id: deploymentId,
          release_id: releaseId,
          fix_release_id: fixReleaseId,
          system_id: systemId,
          subsystem_id: subsystemId,
          external_ref: externalRef.trim() || null,
        };
        // Only include custom_fields when there are values to send; omitting it
        // means the backend's exclude_unset=True will leave existing fields intact.
        if (Object.keys(customFieldValues).length > 0) {
          payload.custom_fields = customFieldValues;
        }
        await dispatch(updateIncident({ id: incidentId, data: payload })).unwrap();
        snackbar.success('Incident updated');
        navigate(`/incidents/${incidentId}`);
      } else {
        const payload: IncidentCreate = {
          title: title.trim(),
          description: description.trim() || undefined,
          severity: severity as IncidentCreate['severity'],
          detected_at: detectedAt ? new Date(detectedAt).toISOString() : undefined,
          environment_id: envId,
          deployment_id: deploymentId,
          release_id: releaseId,
          fix_release_id: fixReleaseId,
          system_id: systemId,
          subsystem_id: subsystemId,
          source: source || 'manual',
          external_ref: externalRef.trim() || null,
          custom_fields: Object.keys(customFieldValues).length > 0 ? customFieldValues : null,
        };
        const result = await dispatch(createIncident(payload)).unwrap();
        snackbar.success('Incident created');
        navigate(`/incidents/${result.id}`);
      }
    } catch (err) {
      snackbar.error(extractErrorMessage(err, 'Failed to save incident'));
    }
  };

  // ── render ────────────────────────────────────────────────────────────────
  if (loadingEdit) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3, maxWidth: 800, mx: 'auto' }}>
      <PageHeader title={isEdit ? 'Edit Incident' : 'New Incident'} />

      <Paper sx={{ p: 3 }}>
        <Stack spacing={2.5}>
          {/* Status chip in edit mode */}
          {isEdit && (
            <Stack direction="row" spacing={1}>
              <Chip label={`Status: ${currentStatus}`} color="primary" size="small" />
              <Chip label={`Severity: ${severity}`} size="small" />
            </Stack>
          )}

          {/* Core fields */}
          <TextField
            label="Title"
            required
            fullWidth
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Brief description of the incident"
          />

          <TextField
            label="Description"
            fullWidth
            multiline
            minRows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Timeline, impact, remediation steps..."
          />

          <TextField
            select
            label="Severity"
            required
            fullWidth
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            {SEVERITIES.map((s) => (
              <MenuItem key={s} value={s}>
                {s}
              </MenuItem>
            ))}
          </TextField>

          {/* Detected date — shown at create, shown read-only-style on edit */}
          <TextField
            label="Detected at"
            type="date"
            fullWidth
            value={detectedAt}
            onChange={(e) => setDetectedAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
            helperText="Defaults to now if left blank"
          />

          {/* Source + external ref */}
          <Stack direction="row" spacing={2}>
            <TextField
              label="Source"
              fullWidth
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="manual"
              helperText="e.g. manual, pagerduty, nagios, jira"
            />
            <TextField
              label="External Ref"
              fullWidth
              value={externalRef}
              onChange={(e) => setExternalRef(e.target.value)}
              placeholder="INC-12345"
              helperText="Reference ID in external system"
            />
          </Stack>

          {/* Searchable pickers */}
          <Typography variant="overline" color="text.secondary">
            Links
          </Typography>

          <Autocomplete
            options={environments}
            getOptionLabel={(e) => e.name}
            value={selectedEnv}
            onChange={(_, next) => setEnvId(next?.id ?? null)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderInput={(params) => (
              <TextField {...params} label="Environment" size="small" />
            )}
          />

          <Autocomplete
            options={deployments}
            getOptionLabel={(d) =>
              `#${d.id}${d.environment_name ? ` — ${d.environment_name}` : ''}${d.release_name ? ` / ${d.release_name}` : ''} (${new Date(d.deployed_at).toLocaleDateString()})`
            }
            value={selectedDeployment}
            onChange={(_, next) => setDeploymentId(next?.id ?? null)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderInput={(params) => (
              <TextField {...params} label="Deployment (causal)" size="small" />
            )}
          />

          <Autocomplete
            options={releases}
            getOptionLabel={(r) => r.name}
            value={selectedRelease}
            onChange={(_, next) => setReleaseId(next?.id ?? null)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderInput={(params) => (
              <TextField {...params} label="Causal release" size="small" />
            )}
          />

          <Autocomplete
            options={releases}
            getOptionLabel={(r) => r.name}
            value={selectedFixRelease}
            onChange={(_, next) => setFixReleaseId(next?.id ?? null)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderInput={(params) => (
              <TextField {...params} label="Fix release" size="small" />
            )}
          />

          <Autocomplete
            options={systems}
            getOptionLabel={(s) => s.name}
            value={selectedSystem}
            onChange={(_, next) => {
              setSystemId(next?.id ?? null);
            }}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Affected system"
                size="small"
                helperText={
                  systemsTruncated ? `Only the first ${systems.length} systems are shown.` : undefined
                }
              />
            )}
          />

          <Autocomplete
            options={subsystems}
            getOptionLabel={(s) => s.name}
            value={selectedSubsystem}
            onChange={(_, next) => setSubsystemId(next?.id ?? null)}
            isOptionEqualToValue={(o, v) => o.id === v.id}
            disabled={systemId == null}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Affected subsystem"
                size="small"
                helperText={systemId == null ? 'Select a system first' : undefined}
              />
            )}
          />

          {/* Lifecycle-driven custom fields */}
          {panelHasAnyFields && (
            <>
              <Typography variant="overline" color="text.secondary">
                Lifecycle fields
              </Typography>
              <LifecycleAwareFieldsPanel
                entityType="incident"
                currentState={currentStatus}
                userRole={userRole}
                fieldPermissions={fieldPermissionsForPanel}
                standardValues={{}}
                customFieldDefinitions={visibleCustomFieldDefs}
                customFieldValues={customFieldValues}
                onStandardChange={() => {/* incident standard fields handled above */}}
                onCustomChange={(key, value) =>
                  setCustomFieldValues((v) => ({ ...v, [key]: value }))
                }
              />
            </>
          )}

          {/* Actions */}
          <Stack direction="row" spacing={2} justifyContent="flex-end" sx={{ pt: 1 }}>
            <Button onClick={() => navigate(isEdit ? `/incidents/${incidentId}` : '/incidents')}>
              Cancel
            </Button>
            <Button variant="contained" onClick={handleSubmit}>
              {isEdit ? 'Save Changes' : 'Create Incident'}
            </Button>
          </Stack>
        </Stack>
      </Paper>
    </Box>
  );
}
