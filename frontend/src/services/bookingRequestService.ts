import api from './api'
import type {
  BookingRequestResponse,
  BookingRequestCreatePayload,
  BookingRequestCreateResponse,
  PreviewConflictsResponse,
  EnvBookingSummary,
} from '../types/bookingRequest'

export const bookingRequestService = {
  list: (): Promise<BookingRequestResponse[]> =>
    api.get('/booking-requests').then((r) => r.data),

  get: (id: number): Promise<BookingRequestResponse> =>
    api.get(`/booking-requests/${id}`).then((r) => r.data),

  create: (payload: BookingRequestCreatePayload): Promise<BookingRequestCreateResponse> =>
    api.post('/booking-requests', payload).then((r) => r.data),

  previewConflicts: (args: {
    environment_ids: number[]
    start_date: string
    end_date: string
  }): Promise<PreviewConflictsResponse> =>
    api.post('/booking-requests/preview-conflicts', args).then((r) => r.data),

  updateStandardFields: (
    id: number,
    values: Record<string, unknown>,
  ): Promise<BookingRequestResponse> =>
    api.patch(`/booking-requests/${id}/standard-fields`, values).then((r) => r.data),

  updateCustomFields: (id: number, values: Record<string, unknown>): Promise<BookingRequestResponse> =>
    api.patch(`/booking-requests/${id}/custom-fields`, { values }).then((r) => r.data),

  addEnvironment: (
    id: number,
    args: { environment_id: number; start_date?: string; end_date?: string },
  ): Promise<EnvBookingSummary> =>
    api.post(`/booking-requests/${id}/environments`, args).then((r) => r.data),

  removeEnvironment: (id: number, bookingId: number): Promise<void> =>
    api.delete(`/booking-requests/${id}/environments/${bookingId}`).then((r) => r.data),
}
