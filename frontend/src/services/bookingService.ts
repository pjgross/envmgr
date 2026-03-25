import api from './api';
import type { BookingResponse, BookingCreate, BookingCreateResponse } from '../types/booking';
import type { BookingStatusHistory, AllowedTransition } from '../types/bookingLifecycle';

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

  approveBooking: (id: number): Promise<BookingResponse> =>
    api.post(`/bookings/${id}/approve`).then((r) => r.data),

  rejectBooking: (id: number): Promise<BookingResponse> =>
    api.post(`/bookings/${id}/reject`).then((r) => r.data),

  cancelBooking: (id: number): Promise<void> =>
    api.post(`/bookings/${id}/cancel`).then((r) => r.data),

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

  updateCustomFields: (id: number, values: Record<string, unknown>): Promise<BookingResponse> =>
    api.patch(`/bookings/${id}/custom-fields`, values).then((r) => r.data),
};
