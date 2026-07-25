import { describe, expect, it } from 'vitest';
import { buildElkGraph, elkToReactFlow, type ElkRenderContext, type RenderSubsystem } from '../topologyElkGraph';
import type { TopologyModel } from '../topologyModel';
import type { ElkNode } from 'elkjs/lib/elk-api';

const comp = (id: number, systemId: number): RenderSubsystem => ({
  id, name: `n${id}`, system_id: systemId, component_type: 'other', technology: null,
});

const model: TopologyModel = {
  systems: [
    { systemId: 2, name: 'Customer', isCurrent: true, collapsed: false, componentCount: 2, components: [comp(5, 2), comp(6, 2)] },
    { systemId: 1, name: 'Mortgage', isCurrent: false, collapsed: true, componentCount: 1, components: [] },
  ],
  edges: [
    { id: '8', source: '5', target: '6', label: 'api_call', aggregatedCount: 1, dependencyId: 8, direction: 'one_way' },
    { id: 'sys-1->5', source: 'sys-1', target: '5', label: 'api_call', aggregatedCount: 1, dependencyId: 10, direction: 'one_way' },
  ],
};

describe('buildElkGraph', () => {
  it('emits a container for an expanded system and a leaf for a collapsed one', () => {
    const g = buildElkGraph(model);
    const ids = (g.children ?? []).map((c) => c.id).sort();
    expect(ids).toEqual(['group-2', 'sys-1']);
    const group = (g.children ?? []).find((c) => c.id === 'group-2')!;
    expect((group.children ?? []).map((c) => c.id).sort()).toEqual(['5', '6']);
    const leaf = (g.children ?? []).find((c) => c.id === 'sys-1')!;
    expect(leaf.children).toBeUndefined();
    expect(leaf.width).toBe(180);
  });

  it('emits one edge per model edge, using resolved endpoints', () => {
    const g = buildElkGraph(model);
    expect((g.edges ?? []).map((e) => `${e.sources[0]}->${e.targets[0]}`).sort()).toEqual([
      '5->6',
      'sys-1->5',
    ]);
  });
});

const laidOut: ElkNode = {
  id: 'root',
  children: [
    { id: 'group-2', x: 300, y: 0, width: 240, height: 140, children: [{ id: '5', x: 12, y: 40, width: 180, height: 70 }, { id: '6', x: 12, y: 40, width: 180, height: 70 }] },
    { id: 'sys-1', x: 0, y: 0, width: 180, height: 70 },
  ],
};
const ctx: ElkRenderContext = {
  systemNames: { '1': 'Mortgage', '2': 'Customer' },
  subsystems: new Map([[5, comp(5, 2)], [6, comp(6, 2)]]),
  colorFor: () => '#616161',
};

describe('elkToReactFlow', () => {
  it('maps a collapsed leaf to a collapsedSystemNode with name + count', () => {
    const { nodes } = elkToReactFlow(laidOut, model, ctx);
    const collapsed = nodes.find((n) => n.id === 'sys-1')!;
    expect(collapsed.type).toBe('collapsedSystemNode');
    expect(collapsed.data).toMatchObject({ systemId: 1, name: 'Mortgage', componentCount: 1 });
  });

  it('maps an expanded container to a group node with its children after it', () => {
    const { nodes } = elkToReactFlow(laidOut, model, ctx);
    const g = nodes.find((n) => n.id === 'group-2')!;
    expect(g.type).toBe('systemGroupNode');
    expect(g.data).toMatchObject({ systemId: 2, isCurrent: true });
    const child = nodes.find((n) => n.id === '5')!;
    expect(child.parentId).toBe('group-2');
    expect(nodes.indexOf(g)).toBeLessThan(nodes.indexOf(child));
  });

  it('builds floating edges from the model', () => {
    const { edges } = elkToReactFlow(laidOut, model, ctx);
    expect(edges.map((e) => e.id).sort()).toEqual(['8', 'sys-1->5']);
    expect(edges.every((e) => e.type === 'floating')).toBe(true);
  });
});
