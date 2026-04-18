import api from './api';
import type { TopologyResponse } from '../types/topology';

export const getSystemTopology = async (systemId: number): Promise<TopologyResponse> => {
  const response = await api.get<TopologyResponse>(`/systems/${systemId}/topology`);
  return response.data;
};
