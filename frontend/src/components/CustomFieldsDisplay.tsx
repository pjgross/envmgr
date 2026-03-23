import { Box, Typography } from '@mui/material';
import type { CustomFieldDefinition } from '../types/customField';

interface CustomFieldsDisplayProps {
  definitions: CustomFieldDefinition[];
  values: Record<string, unknown> | null | undefined;
}

export default function CustomFieldsDisplay({ definitions, values }: CustomFieldsDisplayProps) {
  if (!definitions.length) return null;
  const v = values ?? {};

  return (
    <Box>
      <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        Additional Fields
      </Typography>
      {definitions.map((defn) => {
        const raw = v[defn.field_key];
        let display: string;
        if (raw === null || raw === undefined || raw === '') {
          display = '—';
        } else if (defn.field_type === 'boolean') {
          display = raw ? 'Yes' : 'No';
        } else {
          display = String(raw);
        }
        return (
          <Box key={defn.field_key} sx={{ mb: 1 }}>
            <Typography variant="caption" color="text.secondary">{defn.label}</Typography>
            <Typography variant="body2">{display}</Typography>
          </Box>
        );
      })}
    </Box>
  );
}
