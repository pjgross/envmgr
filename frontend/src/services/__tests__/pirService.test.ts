import { describe, expect, it, vi, beforeEach } from 'vitest';
import api from '../api';
import { pirService } from '../pirService';

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const mockedApi = api as unknown as {
  get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn>;
  patch: ReturnType<typeof vi.fn>; delete: ReturnType<typeof vi.fn>;
};

beforeEach(() => vi.resetAllMocks());

describe('pirService', () => {
  it('creates a finding under its release', async () => {
    mockedApi.post.mockResolvedValue({ data: { id: 7 } });
    await pirService.createFinding(3, { kind: 'went_wrong', title: 'T' });
    expect(mockedApi.post).toHaveBeenCalledWith('/releases/3/pir/findings',
      { kind: 'went_wrong', title: 'T' });
  });

  it('cites an incident against a finding', async () => {
    mockedApi.post.mockResolvedValue({ data: [] });
    await pirService.citeIncident(3, 7, { incident_id: 41, note: 'n' });
    expect(mockedApi.post).toHaveBeenCalledWith('/releases/3/pir/findings/7/incidents',
      { incident_id: 41, note: 'n' });
  });

  it('uncites by incident id, not by a citation id', async () => {
    mockedApi.delete.mockResolvedValue({ data: null });
    await pirService.unciteIncident(3, 7, 41);
    expect(mockedApi.delete).toHaveBeenCalledWith('/releases/3/pir/findings/7/incidents/41');
  });

  it('addresses an action through its finding, not by id alone', async () => {
    mockedApi.patch.mockResolvedValue({ data: { id: 9 } });
    await pirService.updateAction(3, 7, 9, { status: 'done' });
    expect(mockedApi.patch).toHaveBeenCalledWith(
      '/releases/3/pir/findings/7/actions/9', { status: 'done' });
  });

  it('reads the worklist total off X-Total-Count, not off the page length', async () => {
    mockedApi.get.mockResolvedValue({ data: [{ id: 1 }], headers: { 'x-total-count': '97' } });
    const { rows, total } = await pirService.listActions({ limit: 1, offset: 0 });
    expect(rows).toHaveLength(1);
    expect(total).toBe(97);
  });

  it('falls back to the page length when the header is missing', async () => {
    mockedApi.get.mockResolvedValue({ data: [{ id: 1 }, { id: 2 }], headers: {} });
    expect((await pirService.listActions({})).total).toBe(2);
  });

  it('passes the worklist filters through as query params', async () => {
    mockedApi.get.mockResolvedValue({ data: [], headers: {} });
    await pirService.listActions({ status: 'open', overdue: true, limit: 25 });
    expect(mockedApi.get).toHaveBeenCalledWith('/pir-actions',
      { params: { status: 'open', overdue: true, limit: 25 } });
  });
});
