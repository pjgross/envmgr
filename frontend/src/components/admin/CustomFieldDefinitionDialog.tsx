import { useEffect, useState } from 'react';
import {
  Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControlLabel, Switch, TextField, ToggleButton, ToggleButtonGroup,
  Typography, Alert,
} from '@mui/material';
import { useDispatch } from 'react-redux';
import type { AppDispatch } from '../../store';
import { createDefinition, updateDefinition } from '../../store/customFieldSlice';
import type { CustomFieldDefinition, CustomFieldDefinitionCreate, EntityType, FieldType } from '../../types/customField';

const FIELD_KEY_RE = /^[a-z][a-z0-9_]*$/;

function slugify(label: string): string {
  return label.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'field';
}

interface Props {
  open: boolean;
  onClose: () => void;
  entityType: EntityType;
  editTarget: CustomFieldDefinition | null;
}

export default function CustomFieldDefinitionDialog({ open, onClose, entityType, editTarget }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const isEdit = editTarget !== null;

  const [label, setLabel] = useState('');
  const [fieldKey, setFieldKey] = useState('');
  const [keyManuallyEdited, setKeyManuallyEdited] = useState(false);
  const [fieldType, setFieldType] = useState<FieldType>('text');
  const [required, setRequired] = useState(false);
  const [displayOrder, setDisplayOrder] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    if (open) {
      if (editTarget) {
        setLabel(editTarget.label);
        setFieldKey(editTarget.field_key);
        setFieldType(editTarget.field_type);
        setRequired(editTarget.required);
        setDisplayOrder(editTarget.display_order);
        setKeyManuallyEdited(true); // lock key on edit
      } else {
        setLabel('');
        setFieldKey('');
        setKeyManuallyEdited(false);
        setFieldType('text');
        setRequired(false);
        setDisplayOrder(0);
      }
      setError('');
    }
  }, [open, editTarget]);

  const handleLabelChange = (v: string) => {
    setLabel(v);
    if (!keyManuallyEdited && !isEdit) {
      setFieldKey(slugify(v));
    }
  };

  const handleSave = async () => {
    setError('');
    if (!label.trim()) { setError('Label is required'); return; }
    if (!isEdit && !FIELD_KEY_RE.test(fieldKey)) {
      setError('Field key must match ^[a-z][a-z0-9_]*$');
      return;
    }
    try {
      if (isEdit) {
        await dispatch(updateDefinition({
          id: editTarget!.id,
          data: { label, required, display_order: displayOrder },
        })).unwrap();
      } else {
        const payload: CustomFieldDefinitionCreate = {
          entity_type: entityType,
          field_key: fieldKey || undefined,
          label,
          field_type: fieldType,
          required,
          display_order: displayOrder,
        };
        await dispatch(createDefinition(payload)).unwrap();
      }
      onClose();
    } catch (e: unknown) {
      const msg = (e as { message?: string })?.message;
      setError(msg ?? 'Save failed');
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{isEdit ? 'Edit Field' : 'Add Custom Field'}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '20px' }}>
        {error && <Alert severity="error">{error}</Alert>}

        <TextField label="Label *" value={label} onChange={(e) => handleLabelChange(e.target.value)} fullWidth />

        <TextField
          label="Field Key"
          value={fieldKey}
          onChange={(e) => { setFieldKey(e.target.value); setKeyManuallyEdited(true); }}
          fullWidth
          disabled={isEdit}
          helperText={isEdit ? 'Field key cannot be changed after creation' : 'Auto-generated; lowercase letters, digits, underscores'}
          inputProps={{ style: { fontFamily: 'monospace' } }}
        />

        <div>
          <Typography variant="caption" color="text.secondary">Field Type</Typography>
          <ToggleButtonGroup
            value={fieldType}
            exclusive
            onChange={(_, v) => v && setFieldType(v)}
            disabled={isEdit}
            size="small"
            sx={{ display: 'flex', mt: 0.5 }}
          >
            <ToggleButton value="text" sx={{ flex: 1 }}>Text</ToggleButton>
            <ToggleButton value="number" sx={{ flex: 1 }}>Number</ToggleButton>
            <ToggleButton value="boolean" sx={{ flex: 1 }}>Boolean</ToggleButton>
          </ToggleButtonGroup>
          {isEdit && <Typography variant="caption" color="text.secondary">Field type cannot be changed after creation</Typography>}
        </div>

        <TextField
          label="Display Order"
          type="number"
          value={displayOrder}
          onChange={(e) => setDisplayOrder(Number(e.target.value))}
          fullWidth
          size="small"
        />

        <FormControlLabel
          control={<Switch checked={required} onChange={(e) => setRequired(e.target.checked)} />}
          label="Required field"
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained">Save Field</Button>
      </DialogActions>
    </Dialog>
  );
}
