/**
 * The release's post-implementation review.
 *
 * A PIR is a summary plus two lists: what went well and should keep happening,
 * and what went wrong. A went-wrong finding carries the root-cause analysis and
 * the process actions that answer it, plus any incidents cited as evidence.
 *
 * THE REVIEW FIXES THE PROCESS, NOT THE INCIDENT. An incident cited here is
 * evidence that a process failed; it is its own record, raised by the ITIL
 * process or by monitoring, and closing it is not this page's business.
 *
 * NOTHING HERE REFUSES ANYTHING. An incomplete review with overdue actions
 * blocks no release transition and no deployment — see
 * backend/tests/test_pir_records_never_refuses.py.
 *
 * Every mutation re-reads the whole PIR rather than patching local state: seq
 * numbers, overdue verdicts and action counts are all computed server-side, and
 * a locally-patched row would disagree with them the moment anything else moved.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Alert, Box, Button, CircularProgress, Divider, FormControlLabel, Paper, Stack, Switch,
  TextField, Typography,
} from '@mui/material';
import PirActionDialog from './PirActionDialog';
import PirFindingCard from './PirFindingCard';
import PirFindingDialog from './PirFindingDialog';
import { useConfirm } from '../../../hooks/useConfirm';
import { formatApiError } from '../../../services/apiError';
import { pirService } from '../../../services/pirService';
import type { PIR, PirAction, PirFinding, PirFindingKind } from '../../../types/pir';

interface Props {
  releaseId: number;
}

interface FindingDialogState {
  open: boolean;
  kind: PirFindingKind;
  finding: PirFinding | null;
}

interface ActionDialogState {
  open: boolean;
  findingId: number;
  action: PirAction | null;
}

export default function ReleasePirTab({ releaseId }: Props) {
  const { confirm, dialog: confirmDialog } = useConfirm();

  const [pir, setPir] = useState<PIR | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState('');
  const [savingSummary, setSavingSummary] = useState(false);

  const [findingDialog, setFindingDialog] = useState<FindingDialogState>({
    open: false, kind: 'went_wrong', finding: null,
  });
  const [actionDialog, setActionDialog] = useState<ActionDialogState>({
    open: false, findingId: 0, action: null,
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await pirService.getForRelease(releaseId);
      setPir(result);
      setSummary(result?.summary ?? '');
      setError(null);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setLoading(false);
    }
  }, [releaseId]);

  useEffect(() => { void load(); }, [load]);

  const handleCreate = async () => {
    try {
      await pirService.create(releaseId, {});
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const handleSaveSummary = async () => {
    setSavingSummary(true);
    try {
      await pirService.update(releaseId, { summary: summary || null });
      await load();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSavingSummary(false);
    }
  };

  const handleToggleStatus = async (complete: boolean) => {
    try {
      await pirService.update(releaseId, { status: complete ? 'complete' : 'draft' });
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const handleDeleteFinding = async (finding: PirFinding) => {
    if (!(await confirm({
      message: `Delete "${finding.title}" and its actions?`,
      confirmLabel: 'Delete',
      destructive: true,
    }))) return;
    try {
      await pirService.deleteFinding(releaseId, finding.id);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const handleDeleteAction = async (finding: PirFinding, action: PirAction) => {
    if (!(await confirm({
      message: `Delete "${action.title}"?`,
      confirmLabel: 'Delete',
      destructive: true,
    }))) return;
    try {
      await pirService.deleteAction(releaseId, finding.id, action.id);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  const handleRemoveCitation = async (finding: PirFinding, incidentId: number) => {
    try {
      await pirService.unciteIncident(releaseId, finding.id, incidentId);
      await load();
    } catch (err) {
      setError(formatApiError(err));
    }
  };

  if (loading && pir === null) {
    return <Box sx={{ p: 3, textAlign: 'center' }}><CircularProgress /></Box>;
  }

  if (pir === null) {
    return (
      <Paper sx={{ p: 3 }}>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Typography variant="body2" color="text.secondary" gutterBottom>
          No post-implementation review has been started for this release.
        </Typography>
        <Button variant="contained" onClick={handleCreate}>Create PIR</Button>
        {confirmDialog}
      </Paper>
    );
  }

  const wentWell = pir.findings.filter((f) => f.kind === 'went_well');
  const wentWrong = pir.findings.filter((f) => f.kind === 'went_wrong');

  const section = (kind: PirFindingKind, heading: string, findings: PirFinding[]) => (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" gutterBottom>{heading}</Typography>
      <Divider sx={{ mb: 2 }} />
      {findings.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Nothing recorded yet.
        </Typography>
      )}
      {findings.map((finding) => (
        <PirFindingCard
          key={finding.id}
          finding={finding}
          onEdit={(f) => setFindingDialog({ open: true, kind: f.kind, finding: f })}
          onDelete={handleDeleteFinding}
          onAddAction={(f) => setActionDialog({ open: true, findingId: f.id, action: null })}
          onEditAction={(f, a) => setActionDialog({ open: true, findingId: f.id, action: a })}
          onDeleteAction={handleDeleteAction}
          onRemoveCitation={handleRemoveCitation}
        />
      ))}
      <Button onClick={() => setFindingDialog({ open: true, kind, finding: null })}>
        {heading === 'What went well' ? 'Add what went well' : 'Add what went wrong'}
      </Button>
    </Box>
  );

  return (
    <Box>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Paper sx={{ p: 2 }}>
        <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ mb: 1 }}>
          <Typography variant="h6">Summary</Typography>
          <FormControlLabel
            control={
              <Switch
                checked={pir.status === 'complete'}
                onChange={(e) => handleToggleStatus(e.target.checked)}
              />
            }
            label={pir.status === 'complete' ? 'Complete' : 'Draft'}
          />
        </Stack>
        <TextField
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          multiline
          minRows={3}
          fullWidth
          placeholder="How did this release go?"
        />
        <Button sx={{ mt: 1 }} onClick={handleSaveSummary}
                disabled={savingSummary || summary === (pir.summary ?? '')}>
          Save summary
        </Button>
      </Paper>

      {section('went_well', 'What went well', wentWell)}
      {section('went_wrong', 'What went wrong', wentWrong)}

      <PirFindingDialog
        open={findingDialog.open}
        kind={findingDialog.kind}
        finding={findingDialog.finding}
        releaseId={releaseId}
        onClose={() => setFindingDialog((s) => ({ ...s, open: false }))}
        onSaved={load}
      />
      <PirActionDialog
        open={actionDialog.open}
        action={actionDialog.action}
        releaseId={releaseId}
        findingId={actionDialog.findingId}
        onClose={() => setActionDialog((s) => ({ ...s, open: false }))}
        onSaved={load}
      />
      {confirmDialog}
    </Box>
  );
}
