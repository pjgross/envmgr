import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { infrastructureComponentService } from '../infrastructureComponentService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('infrastructureComponentService.listComponents', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: { 'x-total-count': '640' } });
    const result = await infrastructureComponentService.listComponents({});
    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(640);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await infrastructureComponentService.listComponents({})).total).toBe(1);
  });

  it('forwards paging, sorting and filter params', async () => {
    // NOTE: `listComponents` is a pure passthrough — it wraps the params
    // object it's given in `{ params }` with no mapping layer in between —
    // so the object below is exactly the object `mockGet` receives; there is
    // no transformation for this assertion to catch going wrong at runtime.
    // Its only real guard is TypeScript's excess-property check on the
    // object literal passed to `listComponents`, which `npx tsc --noEmit`
    // enforces but `npx vitest run` (esbuild strips types, no type-check)
    // cannot. If a key here is ever renamed or dropped from
    // `listComponents`'s param type, this test will keep passing; only
    // `tsc` will fail.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await infrastructureComponentService.listComponents({
      limit: 25,
      offset: 50,
      sort_by: 'name',
      sort_dir: 'desc',
      search: 'sit',
      component_type: 'server',
      provider: 'aws',
      region: 'eu-west-1',
      source: 'manual',
    });

    expect(mockGet).toHaveBeenCalledWith('/infrastructure-components/', {
      params: {
        limit: 25,
        offset: 50,
        sort_by: 'name',
        sort_dir: 'desc',
        search: 'sit',
        component_type: 'server',
        provider: 'aws',
        region: 'eu-west-1',
        source: 'manual',
      },
    });
  });
});
