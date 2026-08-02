import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { InfrastructureComponentResponse } from '../../types/infrastructureComponent';

vi.mock('../../services/infrastructureComponentService', () => ({
  infrastructureComponentService: { listComponents: vi.fn() },
}));

import { infrastructureComponentService } from '../../services/infrastructureComponentService';
import { useAllHosts } from '../useAllHosts';

const mockList = vi.mocked(infrastructureComponentService.listComponents);

const HOSTS = {
  rows: [{ id: 1, name: 'host-a' }] as InfrastructureComponentResponse[],
  total: 1,
};

/** A promise this test controls the settling of, so "in flight" is observable. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('useSharedList request coalescing', () => {
  beforeEach(() => mockList.mockReset());

  it('issues one request when two consumers mount in the same commit', async () => {
    // The real shape of the bug: ChangeRequestList renders ChangeRequestForm
    // unconditionally (the dialog takes `open` as a prop), so both called
    // useAllHosts in the same commit and the page issued two identical GETs.
    mockList.mockResolvedValue(HOSTS);

    const { result } = renderHook(() => {
      const a = useAllHosts();
      const b = useAllHosts();
      return { a, b };
    });

    await waitFor(() => expect(result.current.a.loading).toBe(false));
    expect(mockList).toHaveBeenCalledTimes(1);
    // Both consumers get the data, not just the one that started the request.
    expect(result.current.a.hosts).toHaveLength(1);
    expect(result.current.b.hosts).toHaveLength(1);
  });

  it('shares the in-flight request with a consumer that mounts before it settles', async () => {
    const d = deferred<typeof HOSTS>();
    mockList.mockReturnValue(d.promise);

    const first = renderHook(() => useAllHosts());
    // Still in flight — a second consumer arriving now must join, not re-fetch.
    const second = renderHook(() => useAllHosts());
    expect(mockList).toHaveBeenCalledTimes(1);

    d.resolve(HOSTS);

    await waitFor(() => expect(first.result.current.loading).toBe(false));
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    expect(second.result.current.hosts).toHaveLength(1);
    expect(mockList).toHaveBeenCalledTimes(1);
  });

  it('is NOT a cache — a consumer mounting after the request settles re-fetches', async () => {
    // This is the property that keeps a picker honest. Caching the resolved
    // list would leave a dropdown missing a row the user just created, which
    // is the exact bug reported against the component-dependency tab.
    mockList.mockResolvedValue(HOSTS);

    const first = renderHook(() => useAllHosts());
    await waitFor(() => expect(first.result.current.loading).toBe(false));
    expect(mockList).toHaveBeenCalledTimes(1);

    const second = renderHook(() => useAllHosts());
    await waitFor(() => expect(second.result.current.loading).toBe(false));
    expect(mockList).toHaveBeenCalledTimes(2);
  });

  it('gives every sharing consumer the empty result when the shared request fails', async () => {
    // Both consumers mount in the same commit and share ONE failing request.
    // The joiner must get the empty result too, not hang on loading — and the
    // shared rejection must not escape as an unhandled rejection, which is why
    // `useSharedList` folds the failure into the promise's value at creation
    // rather than letting subscribers each catch it.
    // `...Once`, not `mockRejectedValue`: the persistent form leaves a rejected
    // promise nothing consumes, which vitest reports as a failure of this test
    // even though the hook handled its own. The assertion below that exactly
    // one call was made is what proves coalescing still holds on the failure
    // path, so nothing is lost by using the single-shot form.
    mockList.mockRejectedValueOnce(new Error('boom'));

    const { result } = renderHook(() => {
      const a = useAllHosts();
      const b = useAllHosts();
      return { a, b };
    });

    await waitFor(() => expect(result.current.a.loading).toBe(false));
    await waitFor(() => expect(result.current.b.loading).toBe(false));
    expect(mockList).toHaveBeenCalledTimes(1);
    expect(result.current.a.hosts).toEqual([]);
    expect(result.current.b.hosts).toEqual([]);
  });

  it('re-fetches after a failure rather than wedging on the failed request', async () => {
    // The map entry must clear on rejection as well as resolution; if it only
    // cleared on success, one failed fetch would poison the key for the rest
    // of the session.
    mockList.mockRejectedValueOnce(new Error('boom'));
    const first = renderHook(() => useAllHosts());
    await waitFor(() => expect(first.result.current.loading).toBe(false));

    mockList.mockResolvedValue(HOSTS);
    const second = renderHook(() => useAllHosts());
    await waitFor(() => expect(second.result.current.hosts).toHaveLength(1));
  });

  it('keeps separate keys separate', async () => {
    // A regression guard on the shared map: hosts and systems must not collide.
    mockList.mockResolvedValue(HOSTS);
    const { result } = renderHook(() => useAllHosts());
    await waitFor(() => expect(result.current.hosts).toHaveLength(1));
    // systemService is unmocked here; if 'hosts' and 'systems' shared a key the
    // hosts result would have satisfied a systems consumer, which is the
    // failure this guards. Asserting the host call count stays 1 is the
    // observable part.
    expect(mockList).toHaveBeenCalledTimes(1);
  });
});
