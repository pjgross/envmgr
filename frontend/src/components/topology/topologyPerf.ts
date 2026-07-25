import { useRef } from 'react';

export const PERF_PREFIX = '[topo-perf]';

export interface LayoutStats {
  layoutMs: number;
  nodeCount: number;
  edgeCount: number;
  engine: 'worker' | 'bundled';
}

/** Dev-only: log ELK layout timing + graph size. No-op in production builds. */
export function logLayout(stats: LayoutStats): void {
  if (!import.meta.env.DEV) return;
  // eslint-disable-next-line no-console
  console.debug(`${PERF_PREFIX} layout`, stats);
}

/** Dev-only: count renders of a node component to validate memoization. */
export function useRenderCount(label: string): void {
  const n = useRef(0);
  n.current += 1;
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.debug(`${PERF_PREFIX} render ${label} #${n.current}`);
  }
}
