import { useState } from 'react';
import {
  Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Stack, TextField, Typography,
} from '@mui/material';
import type { ApiKeyCreatePayload } from '../../types/apiKey';

const AVAILABLE_SCOPES = [
  { key: 'webhooks:deployment', label: 'CI/CD deployment webhook' },
] as const;

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (data: ApiKeyCreatePayload) => Promise<void>;
}

export default function ApiKeyCreateDialog({ open, onClose, onSubmit }: Props) {
  const [name, setName] = useState('');
  const [scopes, setScopes] = useState<string[]>(['webhooks:deployment']);
  const [expiresAt, setExpiresAt] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleClose = () => {
    if (submitting) return;
    setName('');
    setScopes(['webhooks:deployment']);
    setExpiresAt('');
    onClose();
  };

  const handleSubmit = async () => {
    if (!name.trim()) return;
    setSubmitting(true);
    try {
      const iso = expiresAt ? new Date(`${expiresAt}T00:00:00Z`).toISOString() : null;
      await onSubmit({ name: name.trim(), scopes, expires_at: iso });
      handleClose();
    } finally {
      setSubmitting(false);
    }
  };

  const toggleScope = (key: string) => {
    setScopes((prev) => (prev.includes(key) ? prev.filter((s) => s !== key) : [...prev, key]));
  };

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>New API key</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="Name" required fullWidth autoFocus
            value={name} onChange={(e) => setName(e.target.value)}
            inputProps={{ maxLength: 120 }}
          />
          <Box>
            <Typography variant="overline" color="text.secondary">Scopes</Typography>
            {AVAILABLE_SCOPES.map((s) => (
              <FormControlLabel
                key={s.key}
                control={
                  <Checkbox
                    checked={scopes.includes(s.key)}
                    onChange={() => toggleScope(s.key)}
                  />
                }
                label={`${s.label} (${s.key})`}
                sx={{ display: 'block' }}
              />
            ))}
          </Box>
          <TextField
            label="Expires at (optional)"
            type="date"
            fullWidth
            value={expiresAt}
            onChange={(e) => setExpiresAt(e.target.value)}
            InputLabelProps={{ shrink: true }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={submitting}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={!name.trim() || submitting || scopes.length === 0}
        >
          Create
        </Button>
      </DialogActions>
    </Dialog>
  );
}
