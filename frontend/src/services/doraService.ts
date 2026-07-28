import api from './api';
import type { DoraSummary, DoraParams } from '../types/dora';

export const doraService = {
  getSummary: (params: DoraParams) =>
    api.get<DoraSummary>('/metrics/dora', { params }).then((r) => r.data),
  exportUrl: (params: DoraParams) => {
    const q = new URLSearchParams(params as unknown as Record<string, string>).toString();
    return `/api/v1/metrics/dora/export?${q}`;
  },
};
