import ELK from 'elkjs/lib/elk-api';
import ELKBundled from 'elkjs/lib/elk.bundled.js';
import type { Node, Edge } from 'reactflow';
import { buildElkGraph, elkToReactFlow, type ElkRenderContext } from './topologyElkGraph';
import type { TopologyModel } from './topologyModel';
import { logLayout } from './topologyPerf';

interface ElkLike {
  layout: (graph: any) => Promise<any>;
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

  return async function layoutTopology(
    model: TopologyModel,
    ctx: ElkRenderContext,
  ): Promise<{ nodes: Node[]; edges: Edge[] }> {
    const started = performance.now();
    let engine: 'worker' | 'bundled' = 'worker';
    let result: any;
    try {
      worker ??= makeWorker();
      result = await worker.layout(buildElkGraph(model));
    } catch {
      worker = null; // stop using the worker for subsequent layouts
      engine = 'bundled';
      bundled ??= makeBundled();
      result = await bundled.layout(buildElkGraph(model));
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
