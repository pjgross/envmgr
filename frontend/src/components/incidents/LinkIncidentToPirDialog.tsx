/**
 * Cite this incident as evidence on a release's post-implementation review.
 *
 * The incident is its own record — raised by the ITIL incident process or by a
 * monitoring tool — and it already links to the release that caused it and the
 * release that will fix it. What this dialog does is different: where an
 * incident is complex, the release manager uses the PIR to fix the PROCESS that
 * let it reach production. The incident is the evidence that the process failed.
 *
 * SO NOTHING HERE PROMPTS CREATING A RELEASE, and nothing asks for a fix
 * release. The old panel disabled its only button until an incident had a
 * fix_release_id and then anchored the review to that fix — backwards twice
 * over.
 *
 * The release picker offers only releases past their implementation date
 * (`?implemented=true`): a release that has not gone live cannot have caused a
 * production incident. That is a HELPER, not a rule — the server accepts any
 * live release, so a release whose actual date nobody recorded is still
 * reviewable through the API.
 *
 * A release with no PIR yet is not an error and shows no warning: the PIR is
 * created as part of the citation, in one call, in one transaction.
 */
import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Autocomplete, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, FormControlLabel, FormLabel, MenuItem, Radio, RadioGroup, Stack, TextField,
  Typography,
} from '@mui/material';
import { formatApiError } from '../../services/apiError';
import { incidentService } from '../../services/incidentService';
import { pirService } from '../../services/pirService';
import { releaseService } from '../../services/releaseService';
import type { PirFinding } from '../../types/pir';

interface ReleaseOption { id: number; name: string }

type Mode = 'new' | 'existing';

interface Props {
  open: boolean;
  incidentId: number;
  defaultReleaseId: number | null;
  onClose: () => void;
  onLinked: () => void;
}

export default function LinkIncidentToPirDialog({
  open, incidentId, defaultReleaseId, onClose, onLinked,
}: Props) {
  const [releases, setReleases] = useState<ReleaseOption[]>([]);
  const [releaseId, setReleaseId] = useState<number | null>(null);
  const [findings, setFindings] = useState<PirFinding[]>([]);
  const [mode, setMode] = useState<Mode>('new');
  const [findingId, setFindingId] = useState<number | ''>('');
  const [title, setTitle] = useState('');
  const [rootCause, setRootCause] = useState('');
  const [firstAction, setFirstAction] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode('new');
    setFindingId('');
    setTitle('');
    setRootCause('');
    setFirstAction('');
    setNote('');
    setError(null);
    releaseService.list({ implemented: true, limit: 200 })
      .then((paged) => {
        const rows = paged.rows as unknown as ReleaseOption[];
        setReleases(rows);
        // Default to the CAUSAL release, and only if it is actually on offer —
        // preselecting a release the picker cannot show would submit an id the
        // user never saw.
        setReleaseId(rows.some((r) => r.id === defaultReleaseId) ? defaultReleaseId : null);
      })
      .catch((err) => setError(formatApiError(err)));
  }, [open, defaultReleaseId]);

  useEffect(() => {
    if (!open || releaseId === null) {
      setFindings([]);
      return;
    }
    pirService.getForRelease(releaseId)
      .then((pir) => setFindings(pir ? pir.findings : []))
      .catch(() => setFindings([]));
  }, [open, releaseId]);

  // An incident is evidence that something went WRONG. A went-well finding is
  // never a citation target — that would file a production failure in the good
  // column, and the server refuses it anyway.
  const wrongFindings = useMemo(
    () => findings.filter((f) => f.kind === 'went_wrong'),
    [findings],
  );

  const canSubmit = releaseId !== null && !saving
    && (mode === 'existing' ? findingId !== '' : title.trim() !== '');

  const handleSubmit = async () => {
    if (releaseId === null) return;
    setSaving(true);
    setError(null);
    // Exactly one of finding_id / new_finding. Both, or neither, is a 422 — a
    // request that says two things is a bug in the caller.
    const body = mode === 'existing'
      ? { release_id: releaseId, finding_id: Number(findingId), note: note || null }
      : {
        release_id: releaseId,
        new_finding: {
          title,
          detail: null,
          root_cause: rootCause || null,
          // A blank field means NO action, never one with an empty title.
          actions: firstAction.trim() ? [{ title: firstAction }] : [],
        },
        note: note || null,
      };
    try {
      await incidentService.citeOnPir(incidentId, body);
      onLinked();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Link this incident to a review</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2" color="text.secondary">
            The review fixes the process that let this incident reach production. The
            incident stays its own record.
          </Typography>

          <Autocomplete
            options={releases}
            getOptionLabel={(r) => r.name}
            value={releases.find((r) => r.id === releaseId) ?? null}
            onChange={(_, v) => setReleaseId(v ? v.id : null)}
            renderInput={(params) => <TextField {...params} label="Release" required />}
          />

          <FormControl>
            <FormLabel id="pir-citation-mode">Cite</FormLabel>
            <RadioGroup
              aria-labelledby="pir-citation-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
            >
              <FormControlLabel value="new" control={<Radio />}
                                label="A new finding" />
              <FormControlLabel
                value="existing"
                control={<Radio />}
                label="An existing finding"
                disabled={wrongFindings.length === 0}
              />
            </RadioGroup>
            {/* Two different absences, and saying the wrong one is worse than
                saying nothing: before a release is chosen there is no review to
                have findings, and the original copy asserted a fact about "this
                release" when none was selected. Found in the browser — the
                radio's disabled state is identical either way, so no test that
                asserts on it can see the difference. */}
            {releaseId === null ? (
              <Typography variant="caption" color="text.secondary">
                Choose a release to cite one of its existing findings.
              </Typography>
            ) : wrongFindings.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                This release&apos;s review has no went-wrong findings to cite yet.
              </Typography>
            ) : null}
          </FormControl>

          {mode === 'existing' ? (
            <TextField
              label="Finding"
              select
              value={findingId}
              onChange={(e) => setFindingId(Number(e.target.value))}
              fullWidth
            >
              {wrongFindings.map((f) => (
                <MenuItem key={f.id} value={f.id}>{f.title}</MenuItem>
              ))}
            </TextField>
          ) : (
            <>
              <TextField label="What went wrong" value={title}
                         onChange={(e) => setTitle(e.target.value)} required fullWidth />
              <TextField label="Root cause" value={rootCause}
                         onChange={(e) => setRootCause(e.target.value)}
                         multiline minRows={2} fullWidth />
              <TextField label="First action (optional)" value={firstAction}
                         onChange={(e) => setFirstAction(e.target.value)} fullWidth />
            </>
          )}

          <TextField label="Note" value={note} onChange={(e) => setNote(e.target.value)}
                     fullWidth />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={!canSubmit}>Link</Button>
      </DialogActions>
    </Dialog>
  );
}
