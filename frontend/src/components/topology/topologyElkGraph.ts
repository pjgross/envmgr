import type { ElkNode, ElkExtendedEdge } from 'elkjs/lib/elk-api';
import { MarkerType, type Node, type Edge } from 'reactflow';
import type { DependencyDirection } from '../../types/dependency';

/** Minimal shapes the graph builder needs (decoupled from the redux types). */
export interface ElkSubsystem {
  id: number;
  system_id: number;
}
export interface ElkDependency {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
}
export interface ElkGraphInput {
  subsystems: ElkSubsystem[];
  dependencies: ElkDependency[];
  externalSubsystems: ElkSubsystem[];
  externalDependencies: ElkDependency[];
  currentSystemId: number;
}

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;
export const GROUP_LABEL_HEIGHT = 20;

const ROOT_OPTIONS: Record<string, string> = {
  'elk.algorithm': 'layered',
  'elk.direction': 'RIGHT',
  'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
  'elk.layered.spacing.nodeNodeBetweenLayers': '80',
  'elk.spacing.nodeNode': '40',
  'elk.spacing.edgeNode': '20',
  'elk.spacing.edgeEdge': '15',
};

const CONTAINER_OPTIONS: Record<string, string> = {
  // Reserve space at the top for the system label; pad the other sides.
  'elk.padding': `[top=${GROUP_LABEL_HEIGHT + 16},left=12,bottom=12,right=12]`,
};

export function buildElkGraph(input: ElkGraphInput): ElkNode {
  const allSubsystems = [...input.subsystems, ...input.externalSubsystems];
  const allDependencies = [...input.dependencies, ...input.externalDependencies];

  // Group components by system, preserving first-seen order.
  const bySystem = new Map<number, ElkSubsystem[]>();
  for (const s of allSubsystems) {
    if (!bySystem.has(s.system_id)) bySystem.set(s.system_id, []);
    bySystem.get(s.system_id)!.push(s);
  }

  const containers: ElkNode[] = [...bySystem.entries()].map(([sysId, subs]) => ({
    id: `group-${sysId}`,
    layoutOptions: CONTAINER_OPTIONS,
    children: subs.map((s) => ({
      id: String(s.id),
      width: NODE_WIDTH,
      height: NODE_HEIGHT,
    })),
  }));

  const edges: ElkExtendedEdge[] = allDependencies.map((d) => ({
    id: `e${d.id}`,
    sources: [String(d.from_subsystem_id)],
    targets: [String(d.to_subsystem_id)],
  }));

  return {
    id: 'root',
    layoutOptions: ROOT_OPTIONS,
    children: containers,
    edges,
  };
}

/** Full subsystem/dependency data needed to render nodes and edges. */
export interface RenderSubsystem {
  id: number;
  name: string;
  system_id: number;
  component_type: string;
  technology: string | null;
}
export interface RenderDependency {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
  dependency_type: string;
  direction: DependencyDirection;
  label: string | null;
}
export interface ElkRenderContext {
  currentSystemId: number;
  systemNames: Record<string, string>;
  subsystems: Map<number, RenderSubsystem>;
  dependencies: Map<number, RenderDependency>;
  colorFor: (componentType: string) => string;
}

export function elkToReactFlow(
  result: ElkNode,
  ctx: ElkRenderContext
): { nodes: Node[]; edges: Edge[] } {
  const groupNodes: Node[] = [];
  const childNodes: Node[] = [];

  for (const container of result.children ?? []) {
    const sysId = Number(container.id.replace('group-', ''));
    groupNodes.push({
      id: container.id,
      type: 'systemGroupNode',
      position: { x: container.x ?? 0, y: container.y ?? 0 },
      style: { width: container.width ?? 0, height: container.height ?? 0 },
      data: {
        label: ctx.systemNames[String(sysId)] ?? `System ${sysId}`,
        isCurrent: sysId === ctx.currentSystemId,
      },
      selectable: false,
      draggable: false,
    });

    for (const child of container.children ?? []) {
      const sub = ctx.subsystems.get(Number(child.id));
      if (!sub) continue;
      childNodes.push({
        id: child.id,
        type: 'subsystemNode',
        parentId: container.id,
        position: { x: child.x ?? 0, y: child.y ?? 0 },
        data: { label: sub, color: ctx.colorFor(sub.component_type) },
      });
    }
  }

  const edges: Edge[] = (result.edges ?? []).flatMap((e) => {
    const depId = Number(e.id.replace(/^e/, ''));
    const d = ctx.dependencies.get(depId);
    if (!d) return [];
    return [
      {
        id: String(d.id),
        source: String(d.from_subsystem_id),
        target: String(d.to_subsystem_id),
        type: 'floating',
        label: d.label ?? d.dependency_type,
        markerEnd: { type: MarkerType.ArrowClosed },
        ...(d.direction === 'two_way'
          ? { markerStart: { type: MarkerType.ArrowClosed } }
          : {}),
      },
    ];
  });

  // Group nodes must precede child nodes (React Flow parent-before-child rule).
  return { nodes: [...groupNodes, ...childNodes], edges };
}
