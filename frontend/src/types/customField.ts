export type EntityType = 'system' | 'subsystem' | 'environment' | 'booking' | 'change_request' | 'release' | 'release_change' | 'build' | 'deployment' | 'incident';
export type FieldType = 'text' | 'number' | 'boolean';

export interface CustomFieldDefinition {
  id: number;
  tenant_id: number;
  entity_type: EntityType;
  /** Scopes the field to an entity subtype (e.g. release type name); null = all subtypes. */
  entity_subtype: string | null;
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
  entity_subtype?: string | null;
  field_key?: string;
  label: string;
  field_type: FieldType;
  required?: boolean;
  display_order?: number;
}

export interface CustomFieldDefinitionUpdate {
  label?: string;
  entity_subtype?: string | null;
  required?: boolean;
  display_order?: number;
}
