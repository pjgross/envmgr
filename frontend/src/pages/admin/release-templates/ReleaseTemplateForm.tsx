/**
 * ReleaseTemplateForm — create / edit a release template.
 * Metadata + phases editor (reorderable via up/down buttons) + gates editor.
 * Route: /admin/release-templates/new  and  /admin/release-templates/:id
 */
import { useEffect, useMemo, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Box,
  Button,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward';
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import { AppDispatch, RootState } from '../../../store';
import {
  fetchReleaseTemplate,
  createReleaseTemplate,
  updateReleaseTemplate,
  clearDetail,
} from '../../../store/releaseTemplateSlice';
import { fetchGateTypes, selectActiveGateTypes } from '../../../store/gateTypeSlice';
import type {
  ReleaseTemplatePhase,
  ReleaseTemplateGate,
  ReleaseTemplateCreatePayload,
} from '../../../types/releaseTemplate';
import { useSnackbar } from '../../../hooks/useSnackbar';

const RELEASE_TYPES = ['project', 'hotfix', 'patch', 'major', 'minor'];

function emptyPhase(): ReleaseTemplatePhase {
  return { name: '', order: 0, default_duration_days: 5, activities: [] };
}

function emptyGate(): ReleaseTemplateGate {
  return { name: '', phase_name: null, acceptance_criteria: null, gate_type_id: null };
}

export default function ReleaseTemplateForm() {
  const { id } = useParams<{ id: string }>();
  const isNew = id === 'new';
  const templateId = isNew ? null : Number(id);

  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const snackbar = useSnackbar();

  const { detail, loading } = useSelector((s: RootState) => s.releaseTemplate);

  // --- form state ---
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [releaseType, setReleaseType] = useState('project');
  const [phases, setPhases] = useState<ReleaseTemplatePhase[]>([emptyPhase()]);
  const [gates, setGates] = useState<ReleaseTemplateGate[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!isNew && templateId) {
      dispatch(fetchReleaseTemplate(templateId));
    }
    return () => {
      dispatch(clearDetail());
    };
  }, [dispatch, isNew, templateId]);

  useEffect(() => {
    if (detail) {
      setName(detail.name);
      setDescription(detail.description ?? '');
      setReleaseType(detail.release_type);
      setPhases(detail.phases.length > 0 ? detail.phases : [emptyPhase()]);
      setGates(detail.gates);
    }
  }, [detail]);

  // Gate type vocabulary (Phase 9 C2, task 12), reusing Task 9's
  // gateTypeSlice — the same client GatesTable's inline type picker
  // (task 10) already consumes. GET /gate-types is open to any tenant
  // member and returns every type regardless of is_active; that's needed
  // here too, to resolve the NAME of a gate skeleton already pointed at a
  // type that has since been archived.
  const gateTypes = useSelector((s: RootState) => s.gateType.gateTypes);
  const activeGateTypes = selectActiveGateTypes(gateTypes);
  useEffect(() => {
    dispatch(fetchGateTypes());
  }, [dispatch]);

  const gateTypeById = useMemo(
    () => new Map(gateTypes.map((t) => [t.id, t])),
    [gateTypes]
  );
  // A gate skeleton may point at a type that's since been deactivated (or,
  // per Task 6c's grandfathering, one long deleted) — keep it selectable
  // and rendered rather than silently dropped, mirroring GatesTable and
  // the owner/soft-deleted-group carve-out elsewhere in this codebase.
  const assignedTypeIds = useMemo(
    () => new Set(gates.map((g) => g.gate_type_id).filter((id): id is number => id != null)),
    [gates]
  );
  const selectableGateTypes = useMemo(() => {
    const retiredButAssigned = gateTypes.filter(
      (t) => !t.is_active && assignedTypeIds.has(t.id)
    );
    return [...activeGateTypes, ...retiredButAssigned];
  }, [activeGateTypes, gateTypes, assignedTypeIds]);

  // --- phases helpers ---
  const updatePhase = (idx: number, field: keyof ReleaseTemplatePhase, value: unknown) => {
    setPhases((prev) =>
      prev.map((p, i) => (i === idx ? { ...p, [field]: value } : p))
    );
  };

  const movePhase = (idx: number, direction: -1 | 1) => {
    setPhases((prev) => {
      const next = [...prev];
      const target = idx + direction;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next.map((p, i) => ({ ...p, order: i + 1 }));
    });
  };

  const addPhase = () =>
    setPhases((prev) => [...prev, { ...emptyPhase(), order: prev.length + 1 }]);

  const removePhase = (idx: number) =>
    setPhases((prev) => prev.filter((_, i) => i !== idx).map((p, i) => ({ ...p, order: i + 1 })));

  // --- gates helpers ---
  const updateGate = (idx: number, field: keyof ReleaseTemplateGate, value: unknown) => {
    setGates((prev) =>
      prev.map((g, i) => (i === idx ? { ...g, [field]: value } : g))
    );
  };

  const addGate = () => setGates((prev) => [...prev, emptyGate()]);

  const removeGate = (idx: number) => setGates((prev) => prev.filter((_, i) => i !== idx));

  // --- submit ---
  const handleSave = async () => {
    if (!name.trim()) {
      snackbar.error('Template name is required');
      return;
    }
    setSaving(true);
    try {
      const payload: ReleaseTemplateCreatePayload = {
        name: name.trim(),
        description: description.trim() || null,
        release_type: releaseType,
        phases: phases.map((p, i) => ({ ...p, order: i + 1 })),
        gates,
      };

      if (isNew) {
        const created = await dispatch(createReleaseTemplate(payload)).unwrap();
        snackbar.success('Template created');
        navigate(`/admin/release-templates/${created.id}`, { replace: true });
      } else if (templateId) {
        await dispatch(updateReleaseTemplate({ id: templateId, data: payload })).unwrap();
        snackbar.success('Template saved');
      }
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to save template');
    } finally {
      setSaving(false);
    }
  };

  const phaseNames = phases.map((p) => p.name).filter(Boolean);

  return (
    <Box sx={{ p: 3, maxWidth: 900 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1 }}>
        <IconButton size="small" onClick={() => navigate('/admin/release-templates')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h5" sx={{ flexGrow: 1 }}>
          {isNew ? 'New Template' : `Edit Template: ${detail?.name ?? ''}`}
        </Typography>
        <Button variant="contained" onClick={handleSave} disabled={saving || loading}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </Box>

      {/* Metadata */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" fontWeight="medium" gutterBottom>
          Metadata
        </Typography>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField
            label="Name"
            required
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            label="Release Type"
            select
            fullWidth
            value={releaseType}
            onChange={(e) => setReleaseType(e.target.value)}
          >
            {RELEASE_TYPES.map((t) => (
              <MenuItem key={t} value={t}>
                {t}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Description"
            multiline
            rows={3}
            fullWidth
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </Box>
      </Paper>

      {/* Phases */}
      <Paper variant="outlined" sx={{ p: 2, mb: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
          <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
            Phases
          </Typography>
          <Button size="small" startIcon={<AddIcon />} onClick={addPhase}>
            Add Phase
          </Button>
        </Box>

        {phases.map((phase, idx) => (
          <Box key={idx}>
            {idx > 0 && <Divider sx={{ my: 1.5 }} />}
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
              <Box sx={{ display: 'flex', flexDirection: 'column', pt: 0.5 }}>
                <Tooltip title="Move up">
                  <span>
                    <IconButton size="small" onClick={() => movePhase(idx, -1)} disabled={idx === 0}>
                      <ArrowUpwardIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title="Move down">
                  <span>
                    <IconButton
                      size="small"
                      onClick={() => movePhase(idx, 1)}
                      disabled={idx === phases.length - 1}
                    >
                      <ArrowDownwardIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
              </Box>
              <Box sx={{ flexGrow: 1, display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <TextField
                  label={`Phase ${idx + 1} Name`}
                  required
                  size="small"
                  sx={{ flex: '1 1 200px' }}
                  value={phase.name}
                  onChange={(e) => updatePhase(idx, 'name', e.target.value)}
                />
                <TextField
                  label="Default Duration (days)"
                  type="number"
                  size="small"
                  sx={{ flex: '0 0 160px' }}
                  value={phase.default_duration_days}
                  onChange={(e) =>
                    updatePhase(idx, 'default_duration_days', Number(e.target.value))
                  }
                  inputProps={{ min: 1 }}
                />
                <TextField
                  label="Activities (comma separated)"
                  size="small"
                  sx={{ flex: '2 1 300px' }}
                  value={phase.activities.join(', ')}
                  onChange={(e) =>
                    updatePhase(
                      idx,
                      'activities',
                      e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean)
                    )
                  }
                />
              </Box>
              <Tooltip title="Remove phase">
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => removePhase(idx)}
                  disabled={phases.length === 1}
                  sx={{ mt: 0.5 }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        ))}
      </Paper>

      {/* Gates */}
      <Paper variant="outlined" sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 1.5 }}>
          <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
            Gates
          </Typography>
          <Button size="small" startIcon={<AddIcon />} onClick={addGate}>
            Add Gate
          </Button>
        </Box>

        {gates.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            No gates defined. Gates are optional quality checks that can be attached to phases.
          </Typography>
        )}

        {gates.map((gate, idx) => (
          <Box key={idx}>
            {idx > 0 && <Divider sx={{ my: 1.5 }} />}
            <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', flexWrap: 'wrap' }}>
              <TextField
                label="Gate Name"
                required
                size="small"
                sx={{ flex: '1 1 200px' }}
                value={gate.name}
                onChange={(e) => updateGate(idx, 'name', e.target.value)}
              />
              <TextField
                select
                label="Attach to Phase"
                size="small"
                sx={{ flex: '1 1 180px' }}
                value={gate.phase_name ?? ''}
                onChange={(e) =>
                  updateGate(idx, 'phase_name', e.target.value === '' ? null : e.target.value)
                }
              >
                <MenuItem value="">Release-level (no phase)</MenuItem>
                {phaseNames.map((pn) => (
                  <MenuItem key={pn} value={pn}>
                    {pn}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Gate Type"
                size="small"
                sx={{ flex: '1 1 180px' }}
                value={gate.gate_type_id != null ? String(gate.gate_type_id) : ''}
                onChange={(e) =>
                  updateGate(
                    idx,
                    'gate_type_id',
                    e.target.value === '' ? null : Number(e.target.value)
                  )
                }
                SelectProps={{
                  displayEmpty: true,
                  renderValue: (value) => {
                    if (value === '') return 'Untyped';
                    const t = gateTypeById.get(Number(value));
                    return t ? t.name : `Type #${value}`;
                  },
                }}
              >
                <MenuItem value="">Untyped</MenuItem>
                {selectableGateTypes.map((t) => (
                  <MenuItem key={t.id} value={String(t.id)}>
                    {t.name}
                    {!t.is_active ? ' (inactive)' : ''}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Acceptance Criteria"
                size="small"
                multiline
                rows={2}
                sx={{ flex: '2 1 300px' }}
                value={gate.acceptance_criteria ?? ''}
                onChange={(e) =>
                  updateGate(idx, 'acceptance_criteria', e.target.value || null)
                }
              />
              <Tooltip title="Remove gate">
                <IconButton
                  size="small"
                  color="error"
                  onClick={() => removeGate(idx)}
                  sx={{ mt: 0.5 }}
                >
                  <DeleteIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        ))}
      </Paper>
    </Box>
  );
}
