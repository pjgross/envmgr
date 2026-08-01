import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { releaseService } from '../releaseService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('releaseService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '317' },
    });

    const result = await releaseService.list({ limit: 25, offset: 0 });

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(317);
  });

  it('falls back to the row count when the header is absent', async () => {
    // A cross-origin deployment without expose_headers produces exactly this.
    // Reporting NaN would make the grid claim an unknown number of pages.
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });

    const result = await releaseService.list({});

    expect(result.total).toBe(1);
  });

  it('reports a total larger than the returned page', async () => {
    // The guard for a truncated picker: callers can tell they did not get
    // everything. Three call sites discarded this and silently showed 50.
    mockGet.mockResolvedValue({
      data: [{ id: 1, name: 'a' }],
      headers: { 'x-total-count': '312' },
    });

    const result = await releaseService.list({ limit: 200 });

    expect(result.rows).toHaveLength(1);
    expect(result.total).toBe(312);
  });
});
