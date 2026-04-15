import { useState, useEffect } from 'react';
import {
  Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
  MenuItem, Alert, Box, IconButton, Typography, FormControlLabel, Checkbox,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import type { ComponentTypeDefinitionResponse, FieldDefinitionSchema } from '../../types/componentType';

const CATEGORY_OPTIONS = [
  { value: '', label: '(None)' },
  { value: 'web_service', label: 'Web Service' },
  { value: 'api_gateway', label: 'API Gateway' },
  { value: 'database', label: 'Database' },
  { value: 'cache', label: 'Cache' },
  { value: 'message_queue', label: 'Message Queue' },
  { value: 'worker', label: 'Worker' },
  { value: 'frontend', label: 'Frontend' },
  { value: 'other', label: 'Other' },
];

const FIELD_TYPE_OPTIONS = [
  { value: 'text', label: 'Text' },
  { value: 'number', label: 'Number' },
  { value: 'boolean', label: 'Boolean' },
];

const emptyFieldDef = (): FieldDefinitionSchema => ({
  field_key: '',
  label: '',
  field_type: 'text',
  required: false,
  display_order: 0,
});

interface Props {
  open: boolean;
  onClose: () => void;
  onSave: (data: {
    name: string;
    description: string | null;
    category: string | null;
    icon: string | null;
    field_definitions: FieldDefinitionSchema[];
  }) => Promise<void>;
  editTarget: ComponentTypeDefinitionResponse | null;
}

export default function ComponentTypeDialog({ open, onClose, onSave, editTarget }: Props) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [category, setCategory] = useState('');
  const [icon, setIcon] = useState('');
  const [fields, setFields] = useState<FieldDefinitionSchema[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      if (editTarget) {
        setName(editTarget.name);
        setDescription(editTarget.description ?? '');
        setCategory(editTarget.category ?? '');
        setIcon(editTarget.icon ?? '');
        setFields(editTarget.field_definitions ?? []);
      } else {
        setName('');
        setDescription('');
        setCategory('');
        setIcon('');
        setFields([]);
      }
      setError(null);
    }
  }, [open, editTarget]);

  const addField = () => {
    setFields((prev) => [...prev, { ...emptyFieldDef(), display_order: prev.length }]);
  };

  const removeField = (idx: number) => {
    setFields((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateField = (idx: number, key: keyof FieldDefinitionSchema, value: unknown) => {
    setFields((prev) => prev.map((f, i) => (i === idx ? { ...f, [key]: value } : f)));
  };

  const autoKey = (label: string): string =>
    label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSave({
        name: name.trim(),
        description: description.trim() || null,
        category: category || null,
        icon: icon.trim() || null,
        field_definitions: fields.map((f, i) => ({ ...f, display_order: i })),
      });
      onClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{editTarget ? 'Edit Component Type' : 'New Component Type'}</DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: '16px !important' }}>
        {error && <Alert severity="error">{error}</Alert>}

        <TextField label="Name" required value={name} onChange={(e) => setName(e.target.value)} />
        <TextField label="Description" multiline minRows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField
            select label="Category" value={category}
            onChange={(e) => setCategory(e.target.value)} sx={{ flex: 1 }}
          >
            {CATEGORY_OPTIONS.map((o) => (
              <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
            ))}
          </TextField>
          <TextField label="Icon" value={icon} onChange={(e) => setIcon(e.target.value)} sx={{ flex: 1 }} />
        </Box>

        <Box sx={{ mt: 1 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
            <Typography variant="subtitle2">Field Definitions</Typography>
            <Button size="small" startIcon={<AddIcon />} onClick={addField}>Add Field</Button>
          </Box>

          {fields.map((f, idx) => (
            <Box key={idx} sx={{ display: 'flex', gap: 1, mb: 1, alignItems: 'center' }}>
              <TextField
                size="small" label="Label" value={f.label}
                onChange={(e) => {
                  updateField(idx, 'label', e.target.value);
                  if (!editTarget || !f.field_key) {
                    updateField(idx, 'field_key', autoKey(e.target.value));
                  }
                }}
                sx={{ flex: 2 }}
              />
              <TextField
                size="small" label="Key" value={f.field_key}
                onChange={(e) => updateField(idx, 'field_key', e.target.value)}
                sx={{ flex: 2 }}
              />
              <TextField
                select size="small" label="Type" value={f.field_type}
                onChange={(e) => updateField(idx, 'field_type', e.target.value)}
                sx={{ flex: 1 }}
              >
                {FIELD_TYPE_OPTIONS.map((o) => (
                  <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>
                ))}
              </TextField>
              <FormControlLabel
                control={
                  <Checkbox
                    size="small" checked={f.required}
                    onChange={(e) => updateField(idx, 'required', e.target.checked)}
                  />
                }
                label="Req"
                sx={{ mx: 0 }}
              />
              <IconButton size="small" onClick={() => removeField(idx)}><DeleteIcon fontSize="small" /></IconButton>
            </Box>
          ))}
          {fields.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              No field definitions yet. Click "Add Field" to define type-specific fields.
            </Typography>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={!name.trim() || saving}>
          {editTarget ? 'Save' : 'Create'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
