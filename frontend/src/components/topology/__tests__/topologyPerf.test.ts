import { describe, expect, it, vi, afterEach } from 'vitest';
import { logLayout, PERF_PREFIX } from '../topologyPerf';

afterEach(() => vi.restoreAllMocks());

describe('logLayout', () => {
  it('logs layout stats with the perf prefix in dev', () => {
    const spy = vi.spyOn(console, 'debug').mockImplementation(() => {});
    logLayout({ layoutMs: 12.5, nodeCount: 300, edgeCount: 600, engine: 'worker' });
    expect(spy).toHaveBeenCalledOnce();
    expect(spy.mock.calls[0][0]).toContain(PERF_PREFIX);
    expect(spy.mock.calls[0][1]).toMatchObject({ nodeCount: 300, edgeCount: 600, engine: 'worker' });
  });
});
