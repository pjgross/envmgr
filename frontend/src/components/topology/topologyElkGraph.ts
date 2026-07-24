import type { ElkNode, ElkExtendedEdge } from 'elkjs/lib/elk-api';

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
