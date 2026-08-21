/**
 * RecordRollbackDialog — record that a rollback actually happened (Phase 9
 * C4, task 6's POST .../rollback-authorisations).
 *
 * C4 RECORDS; IT NEVER REFUSES. This is an audit trail, not a gate: the
 * backend never inspects plan state, rehearsal state or the readiness
 * verdict before accepting one, and neither does this dialog — the control
 * that opens it must stay enabled even when a release has no rollback plans
 * at all (see RollbackPanel and backend/tests/test_c4_records_never_refuses.py).
 * A rollback with no plan is exactly the case worth recording. `decided_at`
 * may be in the past — this dialog is as often filled in after a 2am
 * recovery as before one.
 */
import { useEffect, useState } from 'react';
import { useDispatch } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormHelperText,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Select,
  TextField,
  type SelectChangeEvent,
} from '@mui/material';

import type { AppDispatch } from '../../store';
import { recordRollbackAuthorisation } from '../../store/rollbackSlice';
import { toDateTimeLocal } from '../../utils/datetime';

interface SystemOption {
  id: number;
  name: string;
}

interface Props {
  releaseId: number;
  open: boolean;
  onClose: () => void;
  systems: SystemOption[];
}

export default function RecordRollbackDialog({ releaseId, open, onClose, systems }: Props) {
  const dispatch = useDispatch<AppDispatch>();

  const [decidedAt, setDecidedAt] = useState('');
  const [trigger, setTrigger] = useState('');
  const [rationale, setRationale] = useState('');
  const [systemIds, setSystemIds] = useState<number[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDecidedAt(toDateTimeLocal(new Date()));
    setTrigger('');
    setRationale('');
    setSystemIds([]);
    setError(null);
  }, [open]);

  const nameFor = (id: number) => systems.find((s) => s.id === id)?.name ?? `#${id}`;

  const handleSystemsChange = (e: SelectChangeEvent<number[]>) => {
    const { value } = e.target;
    setSystemIds(typeof value === 'string' ? value.split(',').map(Number) : value);
  };

  const canSave =
    Boolean(decidedAt) && trigger.trim() !== '' && rationale.trim() !== '' && systemIds.length > 0;

  const handleRecord = async () => {
    if (!canSave) return;
    setSaving(true);
    setError(null);
    const result = await dispatch(
      recordRollbackAuthorisation({
        releaseId,
        data: {
          decided_at: new Date(decidedAt).toISOString(),
          trigger: trigger.trim(),
          rationale: rationale.trim(),
          system_ids: systemIds,
        },
      })
    );
    setSaving(false);
    if (recordRollbackAuthorisation.rejected.match(result)) {
      setError(result.payload ?? 'Failed to record the rollback');
      return;
    }
    onClose();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Record a Rollback</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
        <Alert severity="info">
          This records that a rollback happened, or is about to. It never checks whether a
          plan exists or was agreed, or whether a rehearsal is current — a rollback with no
          plan at all is exactly the case worth keeping a record of.
        </Alert>
        {error && <Alert severity="error">{error}</Alert>}

        <TextField
          label="When"
          type="datetime-local"
          value={decidedAt}
          onChange={(e) => setDecidedAt(e.target.value)}
          disabled={saving}
          InputLabelProps={{ shrink: true }}
          helperText="May be in the past — record a rollback that already happened exactly as it happened."
        />

        <TextField
          label="Trigger"
          required
          value={trigger}
          onChange={(e) => setTrigger(e.target.value)}
          disabled={saving}
          helperText="What set this off — e.g. a failed smoke test, an incident, a customer report."
        />

        <TextField
          label="Rationale"
          required
          multiline
          minRows={3}
          value={rationale}
          onChange={(e) => setRationale(e.target.value)}
          disabled={saving}
        />

        <FormControl>
          <InputLabel id="rollback-systems-label">Affected systems</InputLabel>
          <Select
            labelId="rollback-systems-label"
            multiple
            value={systemIds}
            onChange={handleSystemsChange}
            disabled={saving}
            input={<OutlinedInput label="Affected systems" />}
            renderValue={(selected) => (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {selected.map((id) => (
                  <Chip key={id} size="small" label={nameFor(id)} />
                ))}
              </Box>
            )}
          >
            {systems.map((s) => (
              <MenuItem key={s.id} value={s.id}>
                {s.name}
              </MenuItem>
            ))}
          </Select>
          <FormHelperText>Every system this rollback actually touched.</FormHelperText>
        </FormControl>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="contained" onClick={handleRecord} disabled={!canSave || saving}>
          Record
        </Button>
      </DialogActions>
    </Dialog>
  );
}
