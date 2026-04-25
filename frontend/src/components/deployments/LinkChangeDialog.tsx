import { useEffect, useMemo, useState } from 'react';
import {
  Autocomplete, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  TextField,
} from '@mui/material';
import api from '../../services/api';

interface ChangeRequestOption {
  id: number;
  title: string;
  status: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onSubmit: (changeRequestId: number) => Promise<void>;
}

export default function LinkChangeDialog({ open, onClose, onSubmit }: Props) {
  const [options, setOptions] = useState<ChangeRequestOption[]>([]);
  const [value, setValue] = useState<ChangeRequestOption | null>(null);
  const [input, setInput] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    api.get<ChangeRequestOption[]>('/change-requests', { params: { limit: 100 } })
      .then((r) => setOptions(r.data))
      .catch(() => setOptions([]));
  }, [open]);

  const filtered = useMemo(() => {
    if (!input.trim()) return options;
    const q = input.toLowerCase();
    return options.filter((o) => o.title.toLowerCase().includes(q));
  }, [options, input]);

  const handleSubmit = async () => {
    if (!value) return;
    setSubmitting(true);
    try {
      await onSubmit(value.id);
      setValue(null);
      setInput('');
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Link to a different change request</DialogTitle>
      <DialogContent>
        <Autocomplete
          sx={{ mt: 1 }}
          options={filtered}
          value={value}
          onChange={(_, v) => setValue(v)}
          inputValue={input}
          onInputChange={(_, v) => setInput(v)}
          getOptionLabel={(o) => `${o.title} (${o.status})`}
          renderInput={(params) => <TextField {...params} label="Search change requests" />}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={!value || submitting}>
          Link
        </Button>
      </DialogActions>
    </Dialog>
  );
}
