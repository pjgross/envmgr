/**
 * AddEvidenceDialog — the control that makes gate evidence reachable from
 * the product at all; without it, evidence could only ever be added through
 * the API directly (the "built it and connected it to nothing" defect class
 * B5 shipped four times — see CLAUDE.md).
 */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert,
  Autocomplete,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from '@mui/material';
import type { AppDispatch } from '../../store';
import { addGateEvidence } from '../../store/releaseSlice';
import { useReleaseDeployments } from '../../hooks/useReleaseDeployments';
import { formatDeploymentLabel } from '../../utils/deploymentLabel';
import { useSnackbar } from '../../hooks/useSnackbar';
import type { Deployment } from '../../types/deployment';

interface Props {
  open: boolean;
  onClose: () => void;
  releaseId: number;
  gateId: number;
  /** The gate's type's `expected_evidence` — offered as choices, not a closed
   * vocabulary. Empty for an untyped gate or a type with none configured. */
  expectedEvidence: string[];
  /** The gate's type's `requires_deployment_link` — surfaced as a HINT only.
   * The backend accepts evidence with no deployment_id regardless; a
   * client-side block here would contradict it. */
  requiresDeploymentLink: boolean;
}

export default function AddEvidenceDialog({
  open,
  onClose,
  releaseId,
  gateId,
  expectedEvidence,
  requiresDeploymentLink,
}: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const snackbar = useSnackbar();
  const { deployments } = useReleaseDeployments(releaseId);

  const [kind, setKind] = useState('');
  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setKind('');
    setLabel('');
    setUrl('');
    setDeployment(null);
  };

  const handleClose = () => {
    if (submitting) return;
    reset();
    onClose();
  };

  const handleSubmit = async () => {
    if (!kind.trim() || !label.trim()) return;
    setSubmitting(true);
    try {
      const result = await dispatch(
        addGateEvidence({
          gateId,
          data: {
            kind: kind.trim(),
            label: label.trim(),
            url: url.trim() || undefined,
            deployment_id: deployment?.id ?? undefined,
          },
        })
      );
      if (addGateEvidence.fulfilled.match(result)) {
        snackbar.success('Evidence added');
        reset();
        onClose();
      } else {
        snackbar.error(result.payload ?? 'Failed to add evidence');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>Add Evidence</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Autocomplete
            freeSolo
            options={expectedEvidence}
            inputValue={kind}
            onInputChange={(_, newValue) => setKind(newValue)}
            renderInput={(params) => (
              <TextField {...params} label="Kind" required disabled={submitting} />
            )}
          />

          <TextField
            label="Label"
            required
            fullWidth
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            disabled={submitting}
          />

          <TextField
            label="URL"
            fullWidth
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={submitting}
          />

          <Autocomplete
            options={deployments}
            getOptionLabel={formatDeploymentLabel}
            isOptionEqualToValue={(a, b) => a.id === b.id}
            value={deployment}
            onChange={(_, v) => setDeployment(v)}
            disabled={submitting}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Deployment (optional)"
                placeholder="Search environment or build…"
                helperText="Only relevant if this evidence vouches for a specific deployment — a runbook or licence report vouches for none."
              />
            )}
          />

          {requiresDeploymentLink && !deployment && (
            <Alert severity="info">
              This gate type expects evidence to link a deployment. Evidence
              added with none will show as missing in the readiness check —
              this is a hint, not a requirement, and adding it is still
              allowed.
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={submitting || !kind.trim() || !label.trim()}
        >
          {submitting ? 'Adding…' : 'Add'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
