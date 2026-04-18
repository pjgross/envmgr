import api from './api';
import type {
  ComponentTypeDefinitionResponse,
  ComponentTypeDefinitionCreate,
  ComponentTypeDefinitionUpdate,
} from '../types/componentType';

export const componentTypeService = {
  listTypes: (): Promise<ComponentTypeDefinitionResponse[]> =>
    api.get('/component-types/').then((r) => r.data),

  getType: (id: number): Promise<ComponentTypeDefinitionResponse> =>
    api.get(`/component-types/${id}`).then((r) => r.data),

  createType: (data: ComponentTypeDefinitionCreate): Promise<ComponentTypeDefinitionResponse> =>
    api.post('/component-types/', data).then((r) => r.data),

  updateType: (
    id: number,
    data: ComponentTypeDefinitionUpdate
  ): Promise<ComponentTypeDefinitionResponse> =>
    api.patch(`/component-types/${id}`, data).then((r) => r.data),

  deleteType: (id: number): Promise<void> =>
    api.delete(`/component-types/${id}`).then((r) => r.data),
};
