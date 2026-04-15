export interface FieldDefinitionSchema {
  field_key: string;
  label: string;
  field_type: 'text' | 'number' | 'boolean';
  required: boolean;
  display_order: number;
}

export interface ComponentTypeDefinitionResponse {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  category: string | null;
  icon: string | null;
  field_definitions: FieldDefinitionSchema[] | null;
  created_at: string;
  updated_at: string;
}

export interface ComponentTypeDefinitionCreate {
  name: string;
  description?: string | null;
  category?: string | null;
  icon?: string | null;
  field_definitions?: FieldDefinitionSchema[];
}

export interface ComponentTypeDefinitionUpdate {
  name?: string;
  description?: string | null;
  category?: string | null;
  icon?: string | null;
  field_definitions?: FieldDefinitionSchema[];
}
