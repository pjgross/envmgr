import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, Stack, TextField, Tooltip,
} from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import { useState } from 'react';

interface Props {
  open: boolean;
  rawKey: string;
  onDismiss: () => void;
}

export default function ApiKeyCreatedDialog({ open, rawKey, onDismiss }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(rawKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Dialog open={open} disableEscapeKeyDown maxWidth="sm" fullWidth>
      <DialogTitle>API key created</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Alert severity="warning">
            This is the only time you will see this key. Copy it somewhere
            secure — you will not be able to retrieve it again.
          </Alert>
          <Stack direction="row" spacing={1} alignItems="center">
            <TextField
              fullWidth
              value={rawKey}
              inputProps={{ readOnly: true, style: { fontFamily: 'monospace' } }}
            />
            <Tooltip title={copied ? 'Copied!' : 'Copy to clipboard'}>
              <IconButton onClick={handleCopy} aria-label="copy">
                <ContentCopyIcon />
              </IconButton>
            </Tooltip>
          </Stack>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button variant="contained" onClick={onDismiss}>
          I've copied it
        </Button>
      </DialogActions>
    </Dialog>
  );
}
