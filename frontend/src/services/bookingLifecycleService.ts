import api from './api';
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';

export const bookingLifecycleService = {
  // Lifecycle templates
  listTemplates: (): Promise<BookingLifecycleTemplate[]> =>
    api.get('/tenant/lifecycle-templates').then((r) => r.data),

  createTemplate: (data: Omit<BookingLifecycleTemplate, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>): Promise<BookingLifecycleTemplate> =>
    api.post('/tenant/lifecycle-templates', data).then((r) => r.data),

  updateTemplate: (id: number, data: Partial<Pick<BookingLifecycleTemplate, 'name' | 'description' | 'is_default' | 'definition'>>): Promise<BookingLifecycleTemplate> =>
    api.put(`/tenant/lifecycle-templates/${id}`, data).then((r) => r.data),

  copyTemplate: (id: number, name: string): Promise<BookingLifecycleTemplate> =>
    api.post(`/tenant/lifecycle-templates/${id}/copy`, { name }).then((r) => r.data),

  // Booking types
  listBookingTypes: (): Promise<BookingTypeRecord[]> =>
    api.get('/tenant/booking-types').then((r) => r.data),

  createBookingType: (data: Omit<BookingTypeRecord, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>): Promise<BookingTypeRecord> =>
    api.post('/tenant/booking-types', data).then((r) => r.data),

  updateBookingType: (id: number, data: Partial<Pick<BookingTypeRecord, 'name' | 'description' | 'lifecycle_template_id' | 'color' | 'is_active'>>): Promise<BookingTypeRecord> =>
    api.put(`/tenant/booking-types/${id}`, data).then((r) => r.data),
};
