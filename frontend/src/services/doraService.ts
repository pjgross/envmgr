import api from './api';
import type { DoraSummary, DoraParams } from '../types/dora';

export const doraService = {
  getSummary: (params: DoraParams) =>
    api.get<DoraSummary>('/metrics/dora', { params }).then((r) => r.data),
};
