import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { buildService } from '../buildService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('buildService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '208' },
    });

    const result = await buildService.list({});

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(208);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await buildService.list({})).total).toBe(1);
  });

  it('forwards the sort and search params the grid depends on', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await buildService.list({
      limit: 25,
      offset: 25,
      sort_by: 'git_branch',
      sort_dir: 'asc',
      subsystem_search: 'auth',
      branch: 'main',
    });

    expect(mockGet).toHaveBeenCalledWith('/builds', {
      params: {
        limit: 25,
        offset: 25,
        sort_by: 'git_branch',
        sort_dir: 'asc',
        subsystem_search: 'auth',
        branch: 'main',
      },
    });
  });
});
