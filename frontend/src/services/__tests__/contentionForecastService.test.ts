import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { contentionForecastService } from '../contentionForecastService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

// PINS THE REQUEST SHAPE. contentionForecastSlice.test.ts mocks this
// service, so nothing else in the suite exercises the real
// api.get(url, { params }) call this service makes. FastAPI drops an
// unknown query param SILENTLY — the releases-calendar `from`/`to` vs
// `date_from`/`date_to` mismatch broke that page's date range for months
// while looking correct on screen, because nothing asserted the emitted
// param name. A typo'd `weeks` here would make the backend quietly fall
// back to its own default (6) while the horizon control looks like it
// works. This test — not the slice test — is what would catch that.
describe('contentionForecastService.getHorizon', () => {
  beforeEach(() => mockGet.mockReset());

  it('GETs the contention-horizon route with weeks as the exact param name', async () => {
    mockGet.mockResolvedValue({ data: { count: 4, weeks: 6 } });

    const result = await contentionForecastService.getHorizon(6);

    expect(mockGet).toHaveBeenCalledWith('/bookings/contention-horizon', {
      params: { weeks: 6 },
    });
    // Both fields must reach the caller unchanged — a future edit that
    // drops one off the return value (e.g. `.then((r) => r.data.count)`)
    // must fail here too.
    expect(result).toEqual({ count: 4, weeks: 6 });
  });

  it('passes the given weeks value through unchanged, not a hardcoded default', async () => {
    mockGet.mockResolvedValue({ data: { count: 0, weeks: 12 } });

    const result = await contentionForecastService.getHorizon(12);

    expect(mockGet).toHaveBeenCalledWith('/bookings/contention-horizon', {
      params: { weeks: 12 },
    });
    expect(result).toEqual({ count: 0, weeks: 12 });
  });
});
