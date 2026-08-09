import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { contentionService } from '../contentionService';

vi.mock('../api', () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn() },
}));

const mockGet = vi.mocked(api.get);
const mockPost = vi.mocked(api.post);
const mockPut = vi.mocked(api.put);

const escalation = {
  id: 9,
  booking_id: 42,
  other_booking_id: 43,
  owner_user_id: 7,
  owner_username: 'jsmith',
  escalated_by: 3,
  escalated_by_username: 'admin',
  respond_by: '2026-08-13T00:00:00Z',
  state: 'open',
  bookings_live: true,
  decision_yields_booking_id: null,
  decision_notes: null,
  decided_by: null,
  decided_by_username: null,
  decided_at: null,
};

describe('contentionService.escalate', () => {
  beforeEach(() => mockPost.mockReset());

  it('POSTs to the booking-pair escalate route with owner and deadline in the body', async () => {
    mockPost.mockResolvedValue({ data: escalation });

    const result = await contentionService.escalate(42, 43, {
      owner_user_id: 7,
      respond_by: '2026-08-13T00:00:00Z',
    });

    expect(mockPost).toHaveBeenCalledWith('/bookings/42/contentions/43/escalate', {
      owner_user_id: 7,
      respond_by: '2026-08-13T00:00:00Z',
    });
    expect(result).toEqual(escalation);
  });
});

describe('contentionService.decide', () => {
  beforeEach(() => mockPut.mockReset());

  it('PUTs to the escalation decision route with the yielding booking and notes', async () => {
    const decided = { ...escalation, state: 'answered', decision_yields_booking_id: 43 };
    mockPut.mockResolvedValue({ data: decided });

    const result = await contentionService.decide(9, {
      yields_booking_id: 43,
      notes: 'Project B takes priority this sprint',
    });

    expect(mockPut).toHaveBeenCalledWith('/contention-escalations/9/decision', {
      yields_booking_id: 43,
      notes: 'Project B takes priority this sprint',
    });
    expect(result).toEqual(decided);
  });

  it('passes the body through even when notes is omitted, rather than inventing a key', async () => {
    mockPut.mockResolvedValue({ data: escalation });

    await contentionService.decide(9, { yields_booking_id: 43 });

    expect(mockPut).toHaveBeenCalledWith('/contention-escalations/9/decision', {
      yields_booking_id: 43,
    });
  });
});

describe('contentionService.list', () => {
  beforeEach(() => mockGet.mockReset());

  it('returns rows and the unwindowed total from X-Total-Count', async () => {
    mockGet.mockResolvedValue({ data: [escalation], headers: { 'x-total-count': '12' } });

    const result = await contentionService.list({});

    expect(result.rows).toEqual([escalation]);
    expect(result.total).toBe(12);
  });

  it('falls back to the row count when the header is absent', async () => {
    mockGet.mockResolvedValue({ data: [escalation], headers: {} });

    expect((await contentionService.list({})).total).toBe(1);
  });

  it('forwards the state filter, paging and sort exactly as given — no `all` sentinel', async () => {
    // The worklist's `state` query param has deliberately no 'all' value:
    // omission is the "no selection" sentinel. This asserts the emitted
    // params object, not just that `get` was called, per the sub-project's
    // standing rule that FastAPI drops unknown query params silently.
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await contentionService.list({
      state: 'open',
      limit: 25,
      offset: 50,
      sort_by: 'respond_by',
      sort_dir: 'asc',
    });

    expect(mockGet).toHaveBeenCalledWith('/contention-escalations', {
      params: { state: 'open', limit: 25, offset: 50, sort_by: 'respond_by', sort_dir: 'asc' },
    });
  });

  it('omits the state param entirely rather than sending it as undefined or "all"', async () => {
    mockGet.mockResolvedValue({ data: [], headers: { 'x-total-count': '0' } });

    await contentionService.list({});

    expect(mockGet).toHaveBeenCalledWith('/contention-escalations', { params: {} });
  });
});
