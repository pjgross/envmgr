import api from './api';
import type { BookingResponse, BookingCreate, BookingCreateResponse } from '../types/booking';
import type { BookingStatusHistory, AllowedTransition } from '../types/bookingLifecycle';
import type { ConflictItem, ConflictAck } from '../types/conflict';

export const bookingService = {
  listBookings: (params?: {
    environment_id?: number;
    start?: string;
    end?: string;
    booking_status?: string;
  }): Promise<BookingResponse[]> =>
    api.get('/bookings/', { params }).then((r) => r.data),

  createBooking: (data: BookingCreate): Promise<BookingCreateResponse> =>
    api.post('/bookings/', data).then((r) => r.data),

  getBooking: (id: number): Promise<BookingResponse> =>
    api.get(`/bookings/${id}`).then((r) => r.data),

  deleteOccurrence: (id: number): Promise<void> =>
    api.delete(`/bookings/${id}/occurrence`).then((r) => r.data),

  deleteSeries: (id: number): Promise<void> =>
    api.delete(`/bookings/${id}`).then((r) => r.data),

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
    payload: { willing_to_share: boolean; notes?: string },
  ): Promise<ConflictAck> =>
    api.put(`/bookings/${id}/conflicts/${otherId}/ack`, payload).then((r) => r.data),
};
