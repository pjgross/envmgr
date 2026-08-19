import { describe, expect, it } from 'vitest';
import { bookingColumns, buildCustomFieldColumns } from '../BookingList';
import type { CustomFieldDefinition } from '../../../types/customField';

// Task 6 (B6): the Contention column on the bookings list. `contention_state`
// (Booking.contention_state — see types/booking.ts) is already carried on
// every BookingResponse; this file covers only the new column.
//
// Same technique as bookingListProtection.test.tsx's column-structural
// describe block, and for the same reason: @mui/x-data-grid virtualizes
// columns/cells by container width, jsdom always reports zero width, and a
// real render of this page never gets a cell past the first few columns into
// the DOM — so `renderCell` is invoked directly against a partial row rather
// than via a full DataGrid render.

/**
 * Invoke a column's `renderCell` against a partial row and hand back what it
 * produced.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
function renderColumnCell(col: any, row: Record<string, unknown>): any {
  return col.renderCell?.({ row } as any) as any;
}
/* eslint-enable @typescript-eslint/no-explicit-any */

describe('BookingList — B6 contention column', () => {
  const byField = Object.fromEntries(bookingColumns.map((c) => [c.field, c]));

  it('renders the marker only for contended rows', () => {
    const contended = renderColumnCell(byField.contention_state, { contention_state: 'unowned' });
    const plain = renderColumnCell(byField.contention_state, { contention_state: null });

    expect(contended).not.toBeNull();
    expect(contended.props['data-testid']).toBe('contention-marker');
    expect(plain).toBeNull();
  });

  it('renders nothing at all for a null state', () => {
    // Never an empty chip — an empty chip reads as a state of its own, and
    // no contention is the common case, not the edge case.
    const cell = renderColumnCell(byField.contention_state, { contention_state: null });
    expect(cell).toBeNull();
  });

  it('does not offer Contention as a sortable column', () => {
    // `contention_state` is folded per response AFTER the page is fetched
    // (contention_forecast_service.contention_states_for_bookings) — it is
    // absent from BOOKING_SORTS, so a bare `?sort_by=contention_state` would
    // 422. `/contentions` is the filtering surface; this column offers no
    // filter either.
    expect(byField.contention_state.sortable).toBe(false);
  });

  it('has no custom-field column whose field collides with a static one', () => {
    // BookingList was namespaced cf_<key> in August after a colliding key
    // made MUI emit a visibility change that saveColumnModel PERSISTED,
    // silently hiding a real column. No fixture defines a colliding custom
    // field, so only this structural assertion can catch it.
    const defs = [
      { id: 1, field_key: 'contention_state', label: 'Contention?', field_type: 'text' },
    ] as unknown as CustomFieldDefinition[];
    const cfFields = buildCustomFieldColumns(defs).map((c) => c.field);
    const staticFields = bookingColumns.map((c) => c.field);
    expect(cfFields.some((f) => staticFields.includes(f))).toBe(false);

    const allFields = [...staticFields, ...cfFields];
    expect(new Set(allFields).size).toBe(allFields.length);
  });
});
