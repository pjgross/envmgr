import api from './api';
import type { ContentionHorizon } from '../types/contentionForecast';

// B6 — read-only, like the rest of contention forecasting. `weeks` is
// bounded server-side (ge=1, le=104); this layer does not re-validate it,
// the same way contentionService leaves validation to the backend.
export const contentionForecastService = {
  getHorizon: (weeks: number): Promise<ContentionHorizon> =>
    api
      .get<ContentionHorizon>('/bookings/contention-horizon', { params: { weeks } })
      .then((r) => r.data),
};
