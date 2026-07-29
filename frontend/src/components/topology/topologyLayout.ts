import ELK, { type ElkNode } from 'elkjs/lib/elk-api';
import ELKBundled from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from 'reactflow';
import { buildElkGraph, elkToReactFlow, type ElkRenderContext } from './topologyElkGraph';
import type { TopologyModel } from './topologyModel';
import { logLayout, PERF_PREFIX } from './topologyPerf';

export interface ElkLike {
  layout: (graph: ElkNode) => Promise<ElkNode>;
}

/** Real worker-backed ELK (Vite resolves the worker asset via import.meta.url). */
function defaultWorkerElk(): ElkLike {
  return new ELK({
    workerFactory: () =>
      new Worker(new URL('elkjs/lib/elk-worker.min.js', import.meta.url), { type: 'module' }),
  }) as unknown as ElkLike;
}

/** Main-thread ELK — used as a fallback if the worker path fails. */
function defaultBundledElk(): ElkLike {
  return new ELKBundled() as unknown as ElkLike;
}

export function createLayoutEngine(
  makeWorker: () => ElkLike = defaultWorkerElk,
  makeBundled: () => ElkLike = defaultBundledElk,
) {
  let worker: ElkLike | null = null;
  let bundled: ElkLike | null = null;
  let workerFailed = false; // sticky: once the worker fails, don't rebuild it

  return async function layoutTopology(
    model: TopologyModel,
    ctx: ElkRenderContext,
  ): Promise<{ nodes: Node[]; edges: Edge[] }> {
    const started = performance.now();
    let engine: 'worker' | 'bundled' = workerFailed ? 'bundled' : 'worker';
    const layoutOnMainThread = () => {
      bundled ??= makeBundled();
      return bundled.layout(buildElkGraph(model));
    };

    let result: ElkNode;
    if (workerFailed) {
      result = await layoutOnMainThread();
    } else {
      try {
        worker ??= makeWorker();
        result = await worker.layout(buildElkGraph(model));
      } catch {
        // Worker path is unavailable — fall back to main-thread layout for this
        // and all subsequent layouts, and say so once.
        workerFailed = true;
        worker = null;
        engine = 'bundled';
        if (import.meta.env.DEV) {
          console.debug(`${PERF_PREFIX} worker unavailable — using main-thread ELK`);
        }
        result = await layoutOnMainThread();
      }
    }

    const rf = elkToReactFlow(result, model, ctx);
    logLayout({
      layoutMs: performance.now() - started,
      nodeCount: rf.nodes.length,
      edgeCount: rf.edges.length,
      engine,
    });
    return rf;
  };
}

export const layoutTopology = createLayoutEngine();
