import api from './api';
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';
import type { EntityType } from '../types/customField';

// Lifecycle templates live in a single generic table keyed by `entity_type`.
// The service keeps its original name for back-compat but now passes the
// entity_type on every templates call so change requests (and future entities)
// can share the same admin infrastructure.

export const bookingLifecycleService = {
  // Lifecycle templates — entity_type defaults to 'booking' to preserve
  // back-compat for callers that haven't switched to passing it explicitly.
  listTemplates: (entityType: EntityType = 'booking'): Promise<BookingLifecycleTemplate[]> =>
    api
      .get('/tenant/lifecycle-templates', { params: { entity_type: entityType } })
      .then((r) => r.data),

  getTemplate: (id: number): Promise<BookingLifecycleTemplate> =>
    api.get(`/tenant/lifecycle-templates/${id}`).then((r) => r.data),

  createTemplate: (
    data: Omit<
      BookingLifecycleTemplate,
      'id' | 'tenant_id' | 'entity_type' | 'created_at' | 'updated_at'
    >,
    entityType: EntityType = 'booking'
  ): Promise<BookingLifecycleTemplate> =>
    api
      .post('/tenant/lifecycle-templates', { ...data, entity_type: entityType })
      .then((r) => r.data),

  updateTemplate: (
    id: number,
    data: Partial<
      Pick<
        BookingLifecycleTemplate,
        'name' | 'description' | 'is_default' | 'definition' | 'applies_to_kind'
      >
    >
  ): Promise<BookingLifecycleTemplate> =>
    api.put(`/tenant/lifecycle-templates/${id}`, data).then((r) => r.data),

  copyTemplate: (id: number, name: string): Promise<BookingLifecycleTemplate> =>
    api.post(`/tenant/lifecycle-templates/${id}/copy`, { name }).then((r) => r.data),

  // Booking types — stays booking-specific (CRs don't have a types table).
  listBookingTypes: (): Promise<BookingTypeRecord[]> =>
    api.get('/tenant/booking-types').then((r) => r.data),

  getBookingType: (id: number): Promise<BookingTypeRecord> =>
    api.get(`/tenant/booking-types/${id}`).then((r) => r.data),

  createBookingType: (
    data: Omit<BookingTypeRecord, 'id' | 'tenant_id' | 'created_at' | 'updated_at'>
  ): Promise<BookingTypeRecord> => api.post('/tenant/booking-types', data).then((r) => r.data),

  updateBookingType: (
    id: number,
    data: Partial<
      Pick<
        BookingTypeRecord,
        | 'name'
        | 'description'
        | 'lifecycle_template_id'
        | 'color'
        | 'is_active'
        | 'default_protection_level'
        | 'default_duration_minutes'
      >
    >
  ): Promise<BookingTypeRecord> => api.put(`/tenant/booking-types/${id}`, data).then((r) => r.data),

  deleteTemplate: (id: number): Promise<void> =>
    api.delete(`/tenant/lifecycle-templates/${id}`).then(() => undefined),

  deleteBookingType: (id: number): Promise<void> =>
    api.delete(`/tenant/booking-types/${id}`).then(() => undefined),
};
