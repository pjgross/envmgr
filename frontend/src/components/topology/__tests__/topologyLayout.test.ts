import { describe, expect, it, vi } from 'vitest';
import { createLayoutEngine } from '../topologyLayout';
import type { TopologyModel } from '../topologyModel';
import type { ElkRenderContext } from '../topologyElkGraph';
import type { ElkNode } from 'elkjs/lib/elk-api';

const model: TopologyModel = {
  groups: [
    { groupId: '2', name: 'Customer', isCurrent: true, collapsed: false, componentCount: 1,
      components: [{ id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }] },
  ],
  edges: [],
};

const ctx: ElkRenderContext = {
  subsystems: new Map([[5, { id: 5, name: 'api', system_id: 2, component_type: 'web_service', technology: null }]]),
  colorFor: () => '#000',
};

// A fake ELK that echoes the requested graph back with fixed geometry.
function fakeElk(positions: Record<string, { x: number; y: number }>) {
  return {
    layout: vi.fn(async (graph: ElkNode): Promise<ElkNode> => ({
      ...graph,
      children: (graph.children ?? []).map((c) => ({
        ...c,
        ...(positions[c.id] ?? { x: 0, y: 0 }),
        width: c.width ?? 180,
        height: c.height ?? 70,
        children: (c.children ?? []).map((cc) => ({ ...cc, x: 1, y: 1, width: 180, height: 70 })),
      })),
    })),
  };
}

describe('createLayoutEngine', () => {
  it('composes build → layout → elkToReactFlow into nodes+edges', async () => {
    const worker = fakeElk({ 'group-2': { x: 10, y: 20 } });
    const bundled = fakeElk({});
    const layoutTopology = createLayoutEngine(() => worker, () => bundled);

    const { nodes } = await layoutTopology(model, ctx);
    const group = nodes.find((n) => n.id === 'group-2');
    expect(group?.position).toEqual({ x: 10, y: 20 });
    expect(worker.layout).toHaveBeenCalledOnce();
    expect(bundled.layout).not.toHaveBeenCalled();
  });

  it('falls back to the bundled engine when the worker layout rejects', async () => {
    const worker = { layout: vi.fn().mockRejectedValue(new Error('no Worker in jsdom')) };
    const bundled = fakeElk({ 'group-2': { x: 3, y: 4 } });
    const layoutTopology = createLayoutEngine(() => worker, () => bundled);

    const { nodes } = await layoutTopology(model, ctx);
    expect(worker.layout).toHaveBeenCalledOnce();
    expect(bundled.layout).toHaveBeenCalledOnce();
    expect(nodes.find((n) => n.id === 'group-2')?.position).toEqual({ x: 3, y: 4 });
  });
});
