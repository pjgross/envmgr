// frontend/src/components/CustomFieldsSection.tsx
import { Box, FormControlLabel, Switch, TextField, Typography } from '@mui/material';
import type { CustomFieldDefinition } from '../types/customField';

interface CustomFieldsSectionProps {
  definitions: CustomFieldDefinition[];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}

export default function CustomFieldsSection({ definitions, values, onChange }: CustomFieldsSectionProps) {
  if (definitions.length === 0) return null;

  const handleChange = (key: string, value: unknown) => {
    onChange({ ...values, [key]: value });
  };

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Additional Fields
      </Typography>

      {definitions.map((defn) => {
        const val = values[defn.field_key];
        const label = defn.required ? `${defn.label} *` : defn.label;

        if (defn.field_type === 'boolean') {
          return (
            <FormControlLabel
              key={defn.field_key}
              sx={{ display: 'block', mb: 1 }}
              control={
                <Switch
                  checked={!!val}
                  onChange={(e) => handleChange(defn.field_key, e.target.checked)}
                />
              }
              label={label}
            />
          );
        }

        return (
          <TextField
            key={defn.field_key}
            label={label}
            type={defn.field_type === 'number' ? 'number' : 'text'}
            fullWidth
            size="small"
            sx={{ mb: 1.5 }}
            value={val ?? ''}
            onChange={(e) =>
              handleChange(
                defn.field_key,
                defn.field_type === 'number'
                  ? e.target.value === '' ? null : Number(e.target.value)
                  : e.target.value
              )
            }
          />
        );
      })}
    </Box>
  );
}
