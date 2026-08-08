import { beforeEach, describe, expect, it, vi } from 'vitest';
import api from '../api';
import { agreementGapService } from '../agreementGapService';

vi.mock('../api', () => ({
  default: { put: vi.fn() },
}));

const mockPut = vi.mocked(api.put);

describe('agreementGapService.ackGap', () => {
  beforeEach(() => mockPut.mockReset());

  it('PUTs to the booking-scoped ack route with notes in the body', async () => {
    mockPut.mockResolvedValue({
      data: { notes: 'Reviewed with the project lead', acknowledged_by: 7, acknowledged_at: '2026-08-08T10:00:00Z' },
    });

    const result = await agreementGapService.ackGap(42, 'Reviewed with the project lead');

    expect(mockPut).toHaveBeenCalledWith('/bookings/42/agreement-gap/ack', {
      notes: 'Reviewed with the project lead',
    });
    expect(result).toEqual({
      notes: 'Reviewed with the project lead',
      acknowledged_by: 7,
      acknowledged_at: '2026-08-08T10:00:00Z',
    });
  });

  it('omits notes from the body rather than sending an unexpected key when none is given', async () => {
    // AgreementGapAckUpsert is extra="forbid" server-side, but that only
    // guards against a stray key, not an omitted one — this asserts the
    // client still sends a valid `{ notes: null }` shape rather than, say,
    // an empty object or `undefined`, either of which the schema also
    // accepts (notes defaults to None) but which would be an easy typo to
    // introduce here.
    mockPut.mockResolvedValue({
      data: { notes: null, acknowledged_by: 7, acknowledged_at: '2026-08-08T10:00:00Z' },
    });

    await agreementGapService.ackGap(42);

    expect(mockPut).toHaveBeenCalledWith('/bookings/42/agreement-gap/ack', { notes: null });
  });
});
