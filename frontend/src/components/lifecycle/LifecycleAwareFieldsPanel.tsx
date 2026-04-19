/**
 * LifecycleAwareFieldsPanel
 *
 * Entity-agnostic panel that renders standard fields + custom fields for any
 * lifecycle-managed entity (release, booking, change_request).
 *
 * Field editability is driven by the lifecycle's field_permissions for the
 * current state. Required fields are highlighted with a red asterisk.
 */
import {
  Box,
  FormControlLabel,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import type { CustomFieldDefinition } from '../../types/customField';

export interface FieldPermissionsMap {
  standard_fields?: Record<string, { editable_by: string[] }>;
  custom_fields?: Record<string, { editable_by: string[] }>;
  required_fields?: string[];
}

interface Props {
  entityType: 'release' | 'booking' | 'change_request';
  entitySubtype?: string;
  currentState: string;
  userRole: string;
  /** field_permissions keyed by lifecycle state key */
  fieldPermissions: Record<string, FieldPermissionsMap>;
  standardValues: Record<string, unknown>;
  customFieldDefinitions: CustomFieldDefinition[];
  customFieldValues: Record<string, unknown>;
  onStandardChange: (key: string, value: unknown) => void;
  onCustomChange: (key: string, value: unknown) => void;
}

function isEditable(
  fieldKey: string,
  permMap: Record<string, { editable_by: string[] }> | undefined,
  userRole: string
): boolean {
  if (!permMap) return false;
  const entry = permMap[fieldKey];
  if (!entry) return false;
  return entry.editable_by.includes(userRole) || entry.editable_by.includes('*');
}

function isRequired(fieldKey: string, requiredFields: string[] | undefined): boolean {
  return (requiredFields ?? []).includes(fieldKey);
}

export default function LifecycleAwareFieldsPanel({
  currentState,
  userRole,
  fieldPermissions,
  standardValues,
  customFieldDefinitions,
  customFieldValues,
  onStandardChange,
  onCustomChange,
}: Props) {
  const statePerms: FieldPermissionsMap = fieldPermissions[currentState] ?? {};
  const { standard_fields, custom_fields, required_fields } = statePerms;

  // Collect standard field keys that have an entry in permissions for this state
  const standardKeys = Object.keys(standard_fields ?? {});

  return (
    <Box>
      {/* Standard fields */}
      {standardKeys.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            Standard Fields
          </Typography>
          {standardKeys.map((key) => {
            const editable = isEditable(key, standard_fields, userRole);
            const required = isRequired(key, required_fields);
            const value = standardValues[key];
            const isBool = typeof value === 'boolean';
            const labelText = `${key.replace(/_/g, ' ')}${required ? ' *' : ''}`;

            if (isBool) {
              return (
                <FormControlLabel
                  key={key}
                  sx={{ display: 'block', mb: 1 }}
                  disabled={!editable}
                  control={
                    <Switch
                      checked={!!value}
                      onChange={(e) => onStandardChange(key, e.target.checked)}
                      disabled={!editable}
                    />
                  }
                  label={
                    <Typography
                      component="span"
                      sx={{ color: required && !value ? 'error.main' : 'inherit' }}
                    >
                      {labelText}
                    </Typography>
                  }
                />
              );
            }

            return (
              <TextField
                key={key}
                label={labelText}
                fullWidth
                size="small"
                sx={{ mb: 1.5 }}
                value={value ?? ''}
                disabled={!editable}
                error={required && (value === '' || value === null || value === undefined)}
                onChange={(e) => onStandardChange(key, e.target.value)}
                InputLabelProps={
                  typeof value === 'string' && value !== '' ? { shrink: true } : undefined
                }
              />
            );
          })}
        </Box>
      )}

      {/* Custom fields */}
      {customFieldDefinitions.length > 0 && (
        <Box>
          <Typography variant="overline" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
            Additional Fields
          </Typography>
          {customFieldDefinitions.map((defn) => {
            const editable = isEditable(defn.field_key, custom_fields, userRole);
            const required = isRequired(defn.field_key, required_fields);
            const value = customFieldValues[defn.field_key];
            const labelText = `${defn.label}${required ? ' *' : ''}`;

            if (defn.field_type === 'boolean') {
              return (
                <FormControlLabel
                  key={defn.field_key}
                  sx={{ display: 'block', mb: 1 }}
                  disabled={!editable}
                  control={
                    <Switch
                      checked={!!value}
                      onChange={(e) => onCustomChange(defn.field_key, e.target.checked)}
                      disabled={!editable}
                    />
                  }
                  label={labelText}
                />
              );
            }

            return (
              <TextField
                key={defn.field_key}
                label={labelText}
                type={defn.field_type === 'number' ? 'number' : 'text'}
                fullWidth
                size="small"
                sx={{ mb: 1.5 }}
                value={value ?? ''}
                disabled={!editable}
                error={required && (value === '' || value === null || value === undefined)}
                onChange={(e) =>
                  onCustomChange(
                    defn.field_key,
                    defn.field_type === 'number'
                      ? e.target.value === ''
                        ? null
                        : Number(e.target.value)
                      : e.target.value
                  )
                }
              />
            );
          })}
        </Box>
      )}
    </Box>
  );
}
