import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { bookingService } from '../bookingService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('bookingService.listBookings', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await bookingService.listBookings({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await bookingService.listBookings({})).total).toBe(1);
  });

  it('forwards paging, sorting and the wire-named status filter', async () => {
    // `booking_status`, NOT `status` — the page's local state is called
    // statusFilter and the wire name differs, which is where a careless
    // conversion drops the filter silently.
    //
    // NOTE: `listBookings` is a pure passthrough — it wraps the params object
    // it's given in `{ params }` with no mapping layer in between — so the
    // object below is exactly the object `mockGet` receives; there is no
    // transformation for this assertion to catch going wrong at runtime. Its
    // only real guard is TypeScript's excess-property check on the object
    // literal passed to `listBookings`, which `npx tsc --noEmit` enforces but
    // `npx vitest run` (esbuild strips types, no type-check) cannot. If a key
    // here is ever renamed or dropped from `listBookings`'s param type, this
    // test will keep passing; only `tsc` will fail.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await bookingService.listBookings({
      limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved',
    });

    expect(mockGet).toHaveBeenCalledWith('/bookings/', {
      params: { limit: 25, offset: 50, sort_by: 'end_date', sort_dir: 'desc', booking_status: 'approved' },
    });
  });
});
