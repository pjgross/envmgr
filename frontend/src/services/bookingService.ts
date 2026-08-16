import api from './api';
import type { BookingResponse, BookingCreate, BookingCreateResponse } from '../types/booking';
import type { BookingStatusHistory, AllowedTransition } from '../types/bookingLifecycle';
import type { ConflictItem, ConflictAck, ReceivedFeedbackItem } from '../types/conflict';
import type { Paged } from '../types/pagination';

export const bookingService = {
  listBookings: (params?: {
    environment_id?: number;
    start?: string;
    end?: string;
    booking_status?: string;
    project_id?: number;
    /**
     * A3's usage-agreement filter. `true` = only bookings no live agreement
     * covers; `false` = the exact complement (covered, plus those whose
     * request names no project). OMIT for every booking — `undefined` is
     * dropped by axios, and an empty `?agreement_gap=` is a 422 from
     * FastAPI's `Optional[bool]` rather than an ignored param.
     */
    agreement_gap?: boolean;
    /**
     * B4's protection filter. The query param is `protection`, NOT
     * `protection_level` (that is the column's name) — FastAPI drops an
     * unknown param silently, so the wrong spelling filters nothing while
     * looking right. OMIT for every booking: an empty `?protection=` is a 422
     * from `Optional[Literal["soft","hard"]]`.
     */
    protection?: 'soft' | 'hard';
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }): Promise<Paged<BookingResponse>> =>
    api.get<BookingResponse[]>('/bookings/', { params }).then((r) => ({
      rows: r.data,
      total: Number(r.headers['x-total-count'] ?? r.data.length),
    })),

  createBooking: (data: BookingCreate): Promise<BookingCreateResponse> =>
    api.post('/bookings/', data).then((r) => r.data),

  getBooking: (id: number): Promise<BookingResponse> =>
    api.get(`/bookings/${id}`).then((r) => r.data),

  deleteOccurrence: (id: number): Promise<void> =>
    api.delete(`/bookings/${id}/occurrence`).then((r) => r.data),

  deleteSeries: (id: number): Promise<void> => api.delete(`/bookings/${id}`).then((r) => r.data),

  transitionState: (id: number, to_state: string, notes?: string): Promise<BookingResponse> =>
    api.post(`/bookings/${id}/transition`, { to_state, notes }).then((r) => r.data),

  getHistory: (id: number): Promise<BookingStatusHistory[]> =>
    api.get(`/bookings/${id}/history`).then((r) => r.data),

  getAllowedTransitions: (id: number): Promise<AllowedTransition[]> =>
    api.get(`/bookings/${id}/allowed-transitions`).then((r) => r.data),

  updateStandardFields: (id: number, values: Record<string, unknown>): Promise<BookingResponse> =>
    api.patch(`/bookings/${id}/standard-fields`, values).then((r) => r.data),

  getConflicts: (id: number): Promise<ConflictItem[]> =>
    api.get(`/bookings/${id}/conflicts`).then((r) => r.data),

  acknowledgeConflict: (
    id: number,
    otherId: number,
    payload: { willing_to_share: boolean; notes?: string }
  ): Promise<ConflictAck> =>
    api.put(`/bookings/${id}/conflicts/${otherId}/ack`, payload).then((r) => r.data),

  getReceivedFeedback: (id: number): Promise<ReceivedFeedbackItem[]> =>
    api.get(`/bookings/${id}/received-feedback`).then((r) => r.data),
};
