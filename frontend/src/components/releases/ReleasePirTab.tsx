/**
 * ReleasePirTab — Post-Implementation Review tab for a release.
 *
 * - If no PIR exists: shows an empty state with a "Create PIR" button.
 * - If a PIR exists: shows an editable form (summary, root_cause,
 *   what_went_well, what_went_wrong, action_plan) with Save and status
 *   toggle (Draft ⇄ Complete).
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { pirService } from '../../services/pirService';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { PIR } from '../../types/pir';

interface Props {
  releaseId: number;
}

export default function ReleasePirTab({ releaseId }: Props) {
  const snackbar = useSnackbar();

  const [pir, setPir] = useState<PIR | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);

  // Editable form state — kept in sync with pir when loaded
  const [summary, setSummary] = useState('');
  const [rootCause, setRootCause] = useState('');
  const [whatWentWell, setWhatWentWell] = useState('');
  const [whatWentWrong, setWhatWentWrong] = useState('');
  const [actionPlan, setActionPlan] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await pirService.getForRelease(releaseId);
      setPir(result);
      if (result) {
        setSummary(result.summary ?? '');
        setRootCause(result.root_cause ?? '');
        setWhatWentWell(result.what_went_well ?? '');
        setWhatWentWrong(result.what_went_wrong ?? '');
        setActionPlan(result.action_plan ?? '');
      }
    } catch {
      snackbar.error('Failed to load PIR');
    } finally {
      setLoading(false);
    }
  }, [releaseId, snackbar]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setCreating(true);
    try {
      const created = await pirService.create(releaseId, { status: 'draft' });
      setPir(created);
      setSummary(created.summary ?? '');
      setRootCause(created.root_cause ?? '');
      setWhatWentWell(created.what_went_well ?? '');
      setWhatWentWrong(created.what_went_wrong ?? '');
      setActionPlan(created.action_plan ?? '');
      snackbar.success('PIR created');
    } catch {
      snackbar.error('Failed to create PIR');
    } finally {
      setCreating(false);
    }
  };

  const handleSave = async () => {
    if (!pir) return;
    setSaving(true);
    try {
      const updated = await pirService.update(releaseId, {
        summary: summary || null,
        root_cause: rootCause || null,
        what_went_well: whatWentWell || null,
        what_went_wrong: whatWentWrong || null,
        action_plan: actionPlan || null,
      });
      setPir(updated);
      snackbar.success('PIR saved');
    } catch {
      snackbar.error('Failed to save PIR');
    } finally {
      setSaving(false);
    }
  };

  const handleStatusToggle = async () => {
    if (!pir) return;
    const newStatus = pir.status === 'complete' ? 'draft' : 'complete';
    try {
      const updated = await pirService.update(releaseId, { status: newStatus });
      setPir(updated);
      snackbar.success(
        newStatus === 'complete' ? 'PIR marked complete' : 'PIR returned to draft'
      );
    } catch {
      snackbar.error('Failed to update PIR status');
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (!pir) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Stack spacing={2} alignItems="flex-start">
          <Typography variant="body1" color="text.secondary">
            No PIR for this release.
          </Typography>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={creating}
          >
            {creating ? 'Creating…' : 'Create PIR'}
          </Button>
        </Stack>
      </Paper>
    );
  }

  const isComplete = pir.status === 'complete';

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      {/* Header row: status chip + toggle */}
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Typography variant="subtitle1" fontWeight="medium" sx={{ flexGrow: 1 }}>
          Post-Implementation Review
        </Typography>
        <Chip
          label={isComplete ? 'Complete' : 'Draft'}
          color={isComplete ? 'success' : 'default'}
          size="small"
        />
        {isComplete && pir.completed_at && (
          <Typography variant="caption" color="text.secondary">
            Completed {new Date(pir.completed_at).toLocaleDateString()}
          </Typography>
        )}
        <FormControlLabel
          control={
            <Switch
              checked={isComplete}
              onChange={handleStatusToggle}
              color="success"
              size="small"
            />
          }
          label={isComplete ? 'Mark as draft' : 'Mark complete'}
          labelPlacement="start"
          sx={{ ml: 0 }}
        />
      </Box>

      <Divider sx={{ mb: 2 }} />

      <Stack spacing={2}>
        <TextField
          label="Summary"
          multiline
          minRows={2}
          fullWidth
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="Brief summary of the release outcome"
        />
        <TextField
          label="Root Cause"
          multiline
          minRows={2}
          fullWidth
          value={rootCause}
          onChange={(e) => setRootCause(e.target.value)}
          placeholder="Root cause of any issues encountered"
        />
        <TextField
          label="What Went Well"
          multiline
          minRows={2}
          fullWidth
          value={whatWentWell}
          onChange={(e) => setWhatWentWell(e.target.value)}
          placeholder="Successes and positive outcomes"
        />
        <TextField
          label="What Went Wrong"
          multiline
          minRows={2}
          fullWidth
          value={whatWentWrong}
          onChange={(e) => setWhatWentWrong(e.target.value)}
          placeholder="Issues, delays, or failures encountered"
        />
        <TextField
          label="Action Plan"
          multiline
          minRows={2}
          fullWidth
          value={actionPlan}
          onChange={(e) => setActionPlan(e.target.value)}
          placeholder="Follow-up actions and owners"
        />

        <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}
