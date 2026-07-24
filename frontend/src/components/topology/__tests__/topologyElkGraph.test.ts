import { describe, expect, it } from 'vitest';
import {
  buildElkGraph,
  NODE_WIDTH,
  NODE_HEIGHT,
  elkToReactFlow,
  type ElkGraphInput,
  type ElkRenderContext,
} from '../topologyElkGraph';
import type { ElkNode } from 'elkjs/lib/elk-api';

const sub = (id: number, systemId: number) => ({
  id,
  name: `n${id}`,
  system_id: systemId,
  component_type: 'other',
  technology: null,
});
const dep = (id: number, from: number, to: number) => ({
  id,
  from_subsystem_id: from,
  to_subsystem_id: to,
  dependency_type: 'api_call',
  direction: 'one_way',
  label: null,
});

// Customer(2): API(5)->db(6). External Mortgage(1) sys1 ->5; EnvMgr(19) sys3 ->5.
const input: ElkGraphInput = {
  subsystems: [sub(5, 2), sub(6, 2)],
  dependencies: [dep(8, 5, 6)],
  externalSubsystems: [sub(1, 1), sub(19, 3)],
  externalDependencies: [dep(1, 1, 5), dep(9, 19, 5)],
  currentSystemId: 2,
};

describe('buildElkGraph', () => {
  it('creates one container per system', () => {
    const g = buildElkGraph(input);
    const ids = (g.children ?? []).map((c) => c.id).sort();
    expect(ids).toEqual(['group-1', 'group-2', 'group-3']);
  });

  it('nests each component under its system container', () => {
    const g = buildElkGraph(input);
    const byId = new Map((g.children ?? []).map((c) => [c.id, c]));
    expect((byId.get('group-2')!.children ?? []).map((c) => c.id).sort()).toEqual(['5', '6']);
    expect((byId.get('group-1')!.children ?? []).map((c) => c.id)).toEqual(['1']);
    expect((byId.get('group-3')!.children ?? []).map((c) => c.id)).toEqual(['19']);
  });

  it('emits one edge per dependency (internal + external) with correct endpoints', () => {
    const g = buildElkGraph(input);
    const edges = (g.edges ?? []).map((e) => `${e.sources[0]}->${e.targets[0]}`).sort();
    expect(edges).toEqual(['1->5', '19->5', '5->6']);
  });

  it('gives every component node fixed width/height', () => {
    const g = buildElkGraph(input);
    const child = (g.children ?? [])
      .flatMap((c) => c.children ?? [])
      .find((c) => c.id === '5')!;
    expect(child.width).toBe(NODE_WIDTH);
    expect(child.height).toBe(NODE_HEIGHT);
  });

  it('sets the layered algorithm, RIGHT direction and INCLUDE_CHILDREN on the root', () => {
    const g = buildElkGraph(input);
    expect(g.layoutOptions?.['elk.algorithm']).toBe('layered');
    expect(g.layoutOptions?.['elk.direction']).toBe('RIGHT');
    expect(g.layoutOptions?.['elk.hierarchyHandling']).toBe('INCLUDE_CHILDREN');
  });

  it('applies padding layoutOptions to every container node', () => {
    const g = buildElkGraph(input);
    for (const c of g.children ?? []) {
      expect(c.layoutOptions?.['elk.padding']).toMatch(/top=36/);
    }
  });
});

// A hand-authored laid-out ELK result (as ELK would return it).
const laidOut: ElkNode = {
  id: 'root',
  children: [
    {
      id: 'group-2',
      x: 300, y: 0, width: 240, height: 140,
      children: [
        { id: '5', x: 12, y: 40, width: 180, height: 70 },
        { id: '6', x: 12, y: 40, width: 180, height: 70 }, // coords don't matter for the test
      ],
    },
    {
      id: 'group-1',
      x: 0, y: 0, width: 210, height: 110,
      children: [{ id: '1', x: 12, y: 36, width: 180, height: 70 }],
    },
  ],
  edges: [{ id: 'e1', sources: ['1'], targets: ['5'] }],
};

const ctx: ElkRenderContext = {
  currentSystemId: 2,
  systemNames: { '1': 'Mortgage', '2': 'Customer' },
  subsystems: new Map([
    [5, { id: 5, name: 'API', system_id: 2, component_type: 'api_gateway', technology: null }],
    [6, { id: 6, name: 'db', system_id: 2, component_type: 'database', technology: null }],
    [1, { id: 1, name: 'Mortgage Server', system_id: 1, component_type: 'web_service', technology: null }],
  ]),
  dependencies: new Map([
    [1, { id: 1, from_subsystem_id: 1, to_subsystem_id: 5, dependency_type: 'api_call', direction: 'one_way', label: null }],
  ]),
  colorFor: () => '#616161',
};

describe('elkToReactFlow', () => {
  it('returns group nodes before their child nodes', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const firstChildIdx = nodes.findIndex((n) => n.type === 'subsystemNode');
    const lastGroupIdx = nodes.map((n) => n.type).lastIndexOf('systemGroupNode');
    expect(lastGroupIdx).toBeLessThan(firstChildIdx);
  });

  it('maps container position/size to the group node', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const g = nodes.find((n) => n.id === 'group-2')!;
    expect(g.position).toEqual({ x: 300, y: 0 });
    expect(g.style).toMatchObject({ width: 240, height: 140 });
    expect(g.data).toMatchObject({ label: 'Customer', isCurrent: true });
  });

  it('places children under their parent with ELK-relative positions', () => {
    const { nodes } = elkToReactFlow(laidOut, ctx);
    const child = nodes.find((n) => n.id === '5')!;
    expect(child.parentId).toBe('group-2');
    expect(child.position).toEqual({ x: 12, y: 40 });
    expect(child.data).toMatchObject({ color: '#616161' });
  });

  it('maps each ELK edge to a floating edge with the dependency label/markers', () => {
    const { edges } = elkToReactFlow(laidOut, ctx);
    expect(edges).toHaveLength(1);
    expect(edges[0]).toMatchObject({
      id: '1',
      source: '1',
      target: '5',
      type: 'floating',
      label: 'api_call',
    });
    expect(edges[0].markerStart).toBeUndefined(); // one_way
  });
});
