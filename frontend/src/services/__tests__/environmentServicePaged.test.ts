import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { environmentService } from '../environmentService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('environmentService.listEnvironments', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await environmentService.listEnvironments({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await environmentService.listEnvironments({})).total).toBe(1);
  });

  it('forwards paging, sorting and filter params', async () => {
    // NOTE: `listEnvironments` is a pure passthrough — it wraps the params
    // object it's given in `{ params }` with no mapping layer in between —
    // so the object below is exactly the object `mockGet` receives; there is
    // no transformation for this assertion to catch going wrong at runtime.
    // Its only real guard is TypeScript's excess-property check on the
    // object literal passed to `listEnvironments`, which `npx tsc --noEmit`
    // enforces but `npx vitest run` (esbuild strips types, no type-check)
    // cannot. If a key here is ever renamed or dropped from
    // `listEnvironments`'s param type, this test will keep passing; only
    // `tsc` will fail.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await environmentService.listEnvironments({
      limit: 25,
      offset: 50,
      sort_by: 'name',
      sort_dir: 'desc',
      search: 'sit',
      status: 'active',
      environment_type: 'staging',
    });

    expect(mockGet).toHaveBeenCalledWith('/environments/', {
      params: {
        limit: 25,
        offset: 50,
        sort_by: 'name',
        sort_dir: 'desc',
        search: 'sit',
        status: 'active',
        environment_type: 'staging',
      },
    });
  });
});
