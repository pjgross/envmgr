import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { deploymentService } from '../deploymentService';

vi.mock('../api', () => ({
  default: { get: vi.fn() },
}));

const mockGet = vi.mocked(api.get);

describe('deploymentService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({
      data: [{ id: 1 }, { id: 2 }],
      headers: { 'x-total-count': '412' },
    });

    const result = await deploymentService.list({});

    expect(result.rows).toHaveLength(2);
    expect(result.total).toBe(412);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [{ id: 1 }], headers: {} });
    expect((await deploymentService.list({})).total).toBe(1);
  });

  it('forwards the sort and search params the grid depends on', async () => {
    // toParams is a whitelist. Anything it does not name is dropped in
    // silence — so an unforwarded sort_by renders a sort arrow over data the
    // server never ordered, with no error to notice.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await deploymentService.list({
      limit: 25,
      offset: 50,
      sort_by: 'deployer_name',
      sort_dir: 'asc',
      environment_search: 'prod',
      release_search: 'mortgage',
      status: 'success',
    });

    expect(mockGet).toHaveBeenCalledWith('/deployments', {
      params: {
        limit: 25,
        offset: 50,
        sort_by: 'deployer_name',
        sort_dir: 'asc',
        environment_search: 'prod',
        release_search: 'mortgage',
        status: 'success',
      },
    });
  });
});
