import api from './api';
import type {
  CustomFieldDefinition,
  CustomFieldDefinitionCreate,
  CustomFieldDefinitionUpdate,
  EntityType,
} from '../types/customField';

export const customFieldService = {
  listDefinitions: (entityType: EntityType): Promise<CustomFieldDefinition[]> =>
    api.get('/tenant/fields', { params: { entity_type: entityType } }).then((r) => r.data),

  createDefinition: (data: CustomFieldDefinitionCreate): Promise<CustomFieldDefinition> =>
    api.post('/tenant/fields', data).then((r) => r.data),

  updateDefinition: (
    id: number,
    data: CustomFieldDefinitionUpdate
  ): Promise<CustomFieldDefinition> => api.patch(`/tenant/fields/${id}`, data).then((r) => r.data),

  deleteDefinition: (id: number): Promise<void> =>
    api.delete(`/tenant/fields/${id}`).then((r) => r.data),
};
