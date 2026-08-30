/**
 * Create or edit one finding.
 *
 * `kind` IS NOT A FORM FIELD. It is which list the finding is in, fixed by the
 * section the user added it from — offering it would let someone file a
 * production failure under "keep doing this", dragging its root cause and
 * actions across with it. On edit it is not sent at all: the backend 422s on a
 * change, and sending the unchanged value makes it a change the moment this
 * dialog is reused.
 */
import { useEffect, useState } from 'react';
import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField,
} from '@mui/material';
import { formatApiError } from '../../../services/apiError';
import { pirService } from '../../../services/pirService';
import type { PirFinding, PirFindingKind, PirFindingWrite } from '../../../types/pir';

interface Props {
  open: boolean;
  kind: PirFindingKind;
  finding: PirFinding | null;
  releaseId: number;
  onClose: () => void;
  onSaved: () => void;
}

export default function PirFindingDialog({
  open, kind, finding, releaseId, onClose, onSaved,
}: Props) {
  const [title, setTitle] = useState('');
  const [detail, setDetail] = useState('');
  const [rootCause, setRootCause] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const effectiveKind = finding ? finding.kind : kind;

  useEffect(() => {
    if (!open) return;
    setTitle(finding?.title ?? '');
    setDetail(finding?.detail ?? '');
    setRootCause(finding?.root_cause ?? '');
    setError(null);
  }, [open, finding]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    const shared: PirFindingWrite = {
      title,
      detail: detail || null,
      root_cause: effectiveKind === 'went_wrong' ? (rootCause || null) : null,
    };
    try {
      if (finding) {
        await pirService.updateFinding(releaseId, finding.id, shared);
      } else {
        await pirService.createFinding(releaseId, { ...shared, kind: effectiveKind });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const heading = finding
    ? 'Edit finding'
    : effectiveKind === 'went_well' ? 'Add what went well' : 'Add what went wrong';

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{heading}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)}
                     required fullWidth autoFocus />
          <TextField label="Detail" value={detail} onChange={(e) => setDetail(e.target.value)}
                     multiline minRows={3} fullWidth />
          {effectiveKind === 'went_wrong' && (
            <TextField label="Root cause" value={rootCause}
                       onChange={(e) => setRootCause(e.target.value)}
                       multiline minRows={3} fullWidth />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || !title.trim()}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
