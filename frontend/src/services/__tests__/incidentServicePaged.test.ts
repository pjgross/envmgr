import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { incidentService } from '../incidentService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('incidentService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await incidentService.list({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await incidentService.list({})).total).toBe(1);
  });

  it('forwards paging, sorting and the three select filters', async () => {
    // NOTE: `list` is a pure passthrough — it wraps the params object it's
    // given in `{ params }` with no mapping layer in between — so the object
    // below is exactly the object `mockGet` receives; there is no
    // transformation for this assertion to catch going wrong at runtime.
    // Unlike changeRequestService, the param type here is
    // `Record<string, unknown>`, not a named interface, so there isn't even
    // an excess-property check for `tsc` to enforce — a renamed or dropped
    // key would not be caught by this test, nor by `npx tsc --noEmit`. This
    // test cannot fail at runtime as written; it exists to pin the contract
    // the page conversion depends on, not to guard against regression.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await incidentService.list({
      limit: 25, offset: 0, sort_by: 'severity', sort_dir: 'asc',
      status: 'open', severity: 'P1', system_id: 3,
    });

    expect(mockGet).toHaveBeenCalledWith('/incidents', {
      params: { limit: 25, offset: 0, sort_by: 'severity', sort_dir: 'asc', status: 'open', severity: 'P1', system_id: 3 },
    });
  });
});
