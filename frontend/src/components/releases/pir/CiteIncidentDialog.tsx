/**
 * Cite an incident as evidence for a went-wrong PIR finding, from the RELEASE
 * side.
 *
 * The incident is its own record — raised by the ITIL process or by
 * monitoring — and citing it here closes nothing on it and takes no ownership
 * of it. It records that a production failure is evidence this finding is
 * real. See `LinkIncidentToPirDialog` for the inverse (incident -> PIR) flow:
 * that dialog is oriented incident-first (it always resolves or creates the
 * PIR and the finding too) and has no way to accept a finding that already
 * exists on the page the user is looking at, which is exactly the case here —
 * so this is the smaller, release-side dialog rather than a reuse of that one.
 *
 * The server, not this dialog, decides which finding kinds may be cited
 * against and whether re-citing the same incident is an error — see
 * `pir_finding_service.add_citation`. This control is only ever rendered for a
 * `went_wrong` finding (see `PirFindingCard`), and there is deliberately no
 * client-side "already cited" guard: re-citing updates the note and returns
 * the existing row rather than failing, so refusing it here would contradict
 * the server's own idempotent behaviour.
 */
import { useEffect, useState } from 'react';
import {
  Alert, Autocomplete, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  Stack, TextField,
} from '@mui/material';
import { formatApiError } from '../../../services/apiError';
import { incidentService } from '../../../services/incidentService';
import { pirService } from '../../../services/pirService';
import type { IncidentListRow } from '../../../types/incident';

interface Props {
  open: boolean;
  releaseId: number;
  findingId: number;
  onClose: () => void;
  onCited: () => void;
}

export default function CiteIncidentDialog({
  open, releaseId, findingId, onClose, onCited,
}: Props) {
  const [incidents, setIncidents] = useState<IncidentListRow[]>([]);
  const [incidentsFailed, setIncidentsFailed] = useState(false);
  const [incidentId, setIncidentId] = useState<number | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setIncidentId(null);
    setNote('');
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    incidentService.list()
      .then((paged) => { setIncidents(paged.rows); setIncidentsFailed(false); })
      .catch(() => { setIncidents([]); setIncidentsFailed(true); });
  }, [open]);

  const handleSave = async () => {
    if (incidentId === null) return;
    setSaving(true);
    setError(null);
    try {
      await pirService.citeIncident(releaseId, findingId, {
        incident_id: incidentId,
        note: note.trim() ? note.trim() : null,
      });
      onCited();
      onClose();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Cite an incident</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Autocomplete
            options={incidents}
            getOptionLabel={(i) => `${i.title} (${i.severity})`}
            value={incidents.find((i) => i.id === incidentId) ?? null}
            onChange={(_, v) => setIncidentId(v ? v.id : null)}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Incident"
                required
                autoFocus
                helperText={incidentsFailed ? 'Could not load the incident list' : undefined}
              />
            )}
          />
          <TextField
            label="Note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={2}
            fullWidth
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={incidentId === null || saving}>
          Cite
        </Button>
      </DialogActions>
    </Dialog>
  );
}
