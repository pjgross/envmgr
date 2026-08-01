import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { changeRequestService } from '../changeRequestService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('changeRequestService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await changeRequestService.list({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await changeRequestService.list({})).total).toBe(1);
  });

  it('forwards paging, sorting and the scalar collection filters', async () => {
    // The page filters cr.environment_ids/host_ids client-side today; the
    // server takes scalars. Sending an array here would not filter.
    //
    // NOTE: `list` is a pure passthrough — it wraps the params object it's
    // given in `{ params }` with no mapping layer in between — so the object
    // below is exactly the object `mockGet` receives; there is no
    // transformation for this assertion to catch going wrong at runtime. Its
    // only real guard is TypeScript's excess-property check on the object
    // literal passed to `list`, which `npx tsc --noEmit` enforces but
    // `npx vitest run` (esbuild strips types, no type-check) cannot. If a key
    // here is ever renamed or dropped from `ChangeRequestListFilters`, this
    // test will keep passing; only `tsc` will fail.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await changeRequestService.list({
      limit: 25, offset: 0, sort_by: 'title', sort_dir: 'asc',
      status: 'approved', environment_id: 4, host_id: 9,
    });

    expect(mockGet).toHaveBeenCalledWith('/change-requests', {
      params: { limit: 25, offset: 0, sort_by: 'title', sort_dir: 'asc', status: 'approved', environment_id: 4, host_id: 9 },
    });
  });
});
