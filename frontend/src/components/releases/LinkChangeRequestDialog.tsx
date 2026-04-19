/**
 * LinkChangeRequestDialog — search for an unlinked CR and link it to this release.
 */
import { useEffect, useState } from 'react';
import {
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { changeRequestService } from '../../services/changeRequestService';
import { releaseService } from '../../services/releaseService';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { ChangeRequestResponse } from '../../types/changeRequest';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  onLinked: () => void;
}

export default function LinkChangeRequestDialog({
  open,
  onClose,
  releaseId,
  onLinked,
}: Props) {
  const snackbar = useSnackbar();
  const [allCRs, setAllCRs] = useState<ChangeRequestResponse[]>([]);
  const [selected, setSelected] = useState<ChangeRequestResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    // Load CRs without a release filter — the user can pick any
    changeRequestService.list({}).then(setAllCRs).catch(() => setAllCRs([]));
  }, [open]);

  const handleClose = () => {
    if (submitting) return;
    setSelected(null);
    onClose();
  };

  const handleLink = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      await releaseService.linkChangeRequest(releaseId, selected.id);
      snackbar.success(`CR #${selected.id} linked`);
      setSelected(null);
      onLinked();
      onClose();
    } catch (err) {
      snackbar.error(err instanceof Error ? err.message : 'Failed to link CR');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Link Change Request</DialogTitle>
      <DialogContent>
        <Autocomplete
          options={allCRs}
          getOptionLabel={(cr) => `#${cr.id} — ${cr.title}`}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          value={selected}
          onChange={(_, v) => setSelected(v)}
          renderInput={(params) => (
            <TextField
              {...params}
              label="Change Request"
              placeholder="Search by ID or title"
              sx={{ mt: 1 }}
            />
          )}
          renderOption={(props, cr) => (
            <li {...props} key={cr.id}>
              <Typography variant="body2">
                <strong>#{cr.id}</strong> — {cr.title}{' '}
                <Typography component="span" variant="caption" color="text.secondary">
                  ({cr.status})
                </Typography>
              </Typography>
            </li>
          )}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={!selected || submitting}
          onClick={handleLink}
        >
          {submitting ? 'Linking…' : 'Link'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
