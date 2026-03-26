import { useEffect, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  FormControlLabel,
  TextField,
  Typography,
} from '@mui/material';

import type { AppDispatch, RootState } from '../../store';
import { fetchComponentTypes } from '../../store/componentTypeSlice';
import { updateEnvSubsystem } from '../../store/environmentSlice';
import type { EnvironmentSubsystemResponse } from '../../types/environment';
import type { FieldDefinitionSchema } from '../../types/componentType';

interface Props {
  envId: number;
  subsystem: EnvironmentSubsystemResponse;
  open: boolean;
  onClose: () => void;
}

export default function ComponentTypeAssignDialog({ envId, subsystem, open, onClose }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const { definitions, loading: typesLoading } = useSelector(
    (state: RootState) => state.componentType
  );

  const [selectedTypeId, setSelectedTypeId] = useState<number | ''>(
    subsystem.component_type_definition_id ?? ''
  );
  const [customFields, setCustomFields] = useState<Record<string, unknown>>(
    subsystem.custom_fields ?? {}
  );
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      dispatch(fetchComponentTypes());
      setSelectedTypeId(subsystem.component_type_definition_id ?? '');
      setCustomFields(subsystem.custom_fields ?? {});
      setError('');
    }
  }, [open, dispatch, subsystem]);

  const selectedDefinition = definitions.find((d) => d.id === selectedTypeId);
  const fieldDefs: FieldDefinitionSchema[] = selectedDefinition?.field_definitions ?? [];

  const handleTypeChange = (newTypeId: number | '') => {
    setSelectedTypeId(newTypeId);
    setCustomFields({});
  };

  const handleFieldChange = (key: string, value: unknown) => {
    setCustomFields((prev) => ({ ...prev, [key]: value }));
  };

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await dispatch(
        updateEnvSubsystem({
          envId,
          subsystemId: subsystem.subsystem_id,
          data: {
            component_type_definition_id: selectedTypeId === '' ? null : selectedTypeId,
            custom_fields: selectedTypeId === '' ? null : customFields,
          },
        })
      ).unwrap();
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      setError(message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        Component Type — {subsystem.subsystem_name}
      </DialogTitle>
      <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 2 }}>
        {error && <Alert severity="error">{error}</Alert>}

        <Typography variant="body2" color="text.secondary">
          {subsystem.system_name} / {subsystem.subsystem_name}
        </Typography>

        <FormControl fullWidth>
          <InputLabel>Component Type</InputLabel>
          <Select
            label="Component Type"
            value={selectedTypeId}
            onChange={(e) => handleTypeChange(e.target.value as number | '')}
            disabled={typesLoading}
          >
            <MenuItem value="">
              <em>None</em>
            </MenuItem>
            {definitions.map((def) => (
              <MenuItem key={def.id} value={def.id}>
                {def.name}
                {def.description ? ` — ${def.description}` : ''}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        {fieldDefs.length > 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="subtitle2">Custom Fields</Typography>
            {[...fieldDefs]
              .sort((a, b) => a.display_order - b.display_order)
              .map((field) => {
                if (field.field_type === 'boolean') {
                  return (
                    <FormControlLabel
                      key={field.field_key}
                      control={
                        <Switch
                          checked={Boolean(customFields[field.field_key])}
                          onChange={(e) =>
                            handleFieldChange(field.field_key, e.target.checked)
                          }
                        />
                      }
                      label={`${field.label}${field.required ? ' *' : ''}`}
                    />
                  );
                }
                if (field.field_type === 'number') {
                  return (
                    <TextField
                      key={field.field_key}
                      label={field.label}
                      required={field.required}
                      type="number"
                      value={customFields[field.field_key] ?? ''}
                      onChange={(e) =>
                        handleFieldChange(
                          field.field_key,
                          e.target.value === '' ? null : Number(e.target.value)
                        )
                      }
                      fullWidth
                    />
                  );
                }
                return (
                  <TextField
                    key={field.field_key}
                    label={field.label}
                    required={field.required}
                    value={(customFields[field.field_key] as string) ?? ''}
                    onChange={(e) => handleFieldChange(field.field_key, e.target.value)}
                    fullWidth
                  />
                );
              })}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSave} variant="contained" disabled={saving}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
