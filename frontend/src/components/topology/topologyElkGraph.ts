import type { ElkNode, ElkExtendedEdge } from 'elkjs/lib/elk-api';
import { MarkerType, type Node, type Edge } from 'reactflow';
import type { TopologyModel } from './topologyModel';

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;
export const GROUP_LABEL_HEIGHT = 20;
export const COLLAPSED_WIDTH = 180;
export const COLLAPSED_HEIGHT = 70;

// Gap between adjacent layers, wide enough that an edge label (e.g. "api_call")
// sits clearly between two nodes instead of overlapping their boxes. Applied at
// the root AND on containers — root-level spacing does not reach inside a
// system's own components.
const LAYER_SPACING = '120';

export const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.layered.spacing.nodeNodeBetweenLayers': LAYER_SPACING,
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '15',
};

export const CONTAINER_OPTIONS: Record<string, string> = {
  // Reserve space at the top for the system label; pad the other sides.
  'elk.padding': `[top=${GROUP_LABEL_HEIGHT + 16},left=12,bottom=12,right=12]`,
  'elk.layered.spacing.nodeNodeBetweenLayers': LAYER_SPACING,
};

export function buildElkGraph(model: TopologyModel): ElkNode {
  const children: ElkNode[] = model.groups.map((g) =>
    g.collapsed
      ? { id: `sys-${g.groupId}`, width: COLLAPSED_WIDTH, height: COLLAPSED_HEIGHT }
      : {
          id: `group-${g.groupId}`,
          layoutOptions: CONTAINER_OPTIONS,
          children: g.components.map((c) => ({
            id: String(c.id),
            width: NODE_WIDTH,
            height: NODE_HEIGHT,
          })),
        }
  );

  const edges: ElkExtendedEdge[] = model.edges.map((e) => ({
    id: e.id,
    sources: [e.source],
    targets: [e.target],
  }));

  return { id: 'root', layoutOptions: ROOT_OPTIONS, children, edges };
}

/** Full subsystem/dependency data needed to render nodes and edges. */
export interface RenderSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
  is_mocked?: boolean;
}
export interface ElkRenderContext {
  subsystems: Map<number, RenderSubsystem>;
  colorFor: (componentType: string) => string;
}

export function elkToReactFlow(
  result: ElkNode,
  model: TopologyModel,
  ctx: ElkRenderContext
): { nodes: Node[]; edges: Edge[] } {
  const groupById = new Map(model.groups.map((g) => [g.groupId, g]));
  const topNodes: Node[] = [];
  const childNodes: Node[] = [];

  for (const node of result.children ?? []) {
    if (node.id.startsWith('sys-')) {
      const groupId = node.id.replace('sys-', '');
      const g = groupById.get(groupId);
      if (!g) continue;
      topNodes.push({
        id: node.id,
        type: 'collapsedSystemNode',
        position: { x: node.x ?? 0, y: node.y ?? 0 },
        data: { groupId, name: g.name, componentCount: g.componentCount, isCurrent: g.isCurrent },
        selectable: false,
        draggable: false,
      });
      continue;
    }
    const groupId = node.id.replace('group-', '');
    const g = groupById.get(groupId);
    topNodes.push({
      id: node.id,
      type: 'systemGroupNode',
      position: { x: node.x ?? 0, y: node.y ?? 0 },
      style: { width: node.width ?? 0, height: node.height ?? 0 },
      data: {
        label: g?.name ?? `Group ${groupId}`,
        isCurrent: g?.isCurrent ?? false,
        groupId,
      },
      selectable: false,
      draggable: false,
    });
    for (const child of node.children ?? []) {
      const sub = ctx.subsystems.get(Number(child.id));
      if (!sub) continue;
      childNodes.push({
        id: child.id,
        type: 'subsystemNode',
        parentId: node.id,
        position: { x: child.x ?? 0, y: child.y ?? 0 },
        data: { label: sub, color: ctx.colorFor(sub.component_type) },
      });
    }
  }

  // Edges come from the model (topology), not result.edges — ELK's result only supplies node geometry.
  const edges: Edge[] = model.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: 'floating',
    label: e.label,
    markerEnd: { type: MarkerType.ArrowClosed },
    ...(e.direction === 'two_way' && e.aggregatedCount === 1
      ? { markerStart: { type: MarkerType.ArrowClosed } }
      : {}),
  }));

  return { nodes: [...topNodes, ...childNodes], edges };
}
