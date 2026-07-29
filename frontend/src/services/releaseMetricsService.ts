import api from './api';
import type { ReleaseMetrics, BookingConflictRow, ReleaseMetricsParams } from '../types/releaseMetrics';

export const releaseMetricsService = {
  releases: (params: ReleaseMetricsParams) =>
    api.get<ReleaseMetrics>('/metrics/releases', { params }).then((r) => r.data),
  conflicts: (params: ReleaseMetricsParams) =>
    api.get<BookingConflictRow[]>('/metrics/bookings/conflicts', { params }).then((r) => r.data),
};
