export type EntityType = 'system' | 'subsystem' | 'environment' | 'booking' | 'change_request';
export type FieldType = 'text' | 'number' | 'boolean';

export interface CustomFieldDefinition {
  id: number;
  tenant_id: number;
  entity_type: EntityType;
  field_key: string;
  label: string;
  field_type: FieldType;
  required: boolean;
  display_order: number;
  options: Record<string, unknown> | null;
  lifecycle_states: string[] | null;
  created_at: string;
  updated_at: string;
}

export interface CustomFieldDefinitionCreate {
  entity_type: EntityType;
  field_key?: string;
  label: string;
  field_type: FieldType;
  required?: boolean;
  display_order?: number;
}

export interface CustomFieldDefinitionUpdate {
  label?: string;
  required?: boolean;
  display_order?: number;
}
