import type { VisibleSubsystem, VisibleDependency, VisibilityInput } from './topologyVisibility';

export interface HostGroupMeta {
  name: string;
  isCurrent: boolean;
}

export interface HostGraph {
  /** Synthetic graph: per-host subsystem instances + fanned-out dependencies. */
  graph: VisibilityInput;
  /** synthetic node id -> host group key */
  hostKeyById: Map<number, string>;
  /** host group key -> display metadata */
  hostMeta: Map<string, HostGroupMeta>;
  /** synthetic edge id -> real dependency id (for the detail pane) */
  edgeDepResolver: Map<number, number>;
}

const UNASSIGNED = 'unassigned';
const EXTERNAL = 'external';

/**
 * Regroup an environment topology by deployment host. Each subsystem is duplicated
 * into one synthetic node per host it runs on; dependencies fan out across the
 * cartesian product of their endpoints' instances. Node ids and edge ids are freshly
 * minted (disjoint counters) so the numeric-keyed core pipeline stays valid, and the
 * returned maps resolve synthetic ids back to host groups and real dependencies.
 */
export function buildHostGraph(input: VisibilityInput): HostGraph {
  const hostKeyById = new Map<number, string>();
  const hostMeta = new Map<string, HostGroupMeta>();
  const edgeDepResolver = new Map<number, number>();
  // Keyed by real (source) subsystem id -> its synthetic per-host instances. Relies on
  // internal and external subsystems occupying disjoint id-spaces (holds in this domain),
  // so a real id maps unambiguously to one set of instances.
  const instancesOf = new Map<number, VisibleSubsystem[]>();

  let nodeSeq = 1;
  let edgeSeq = 1;

  const addInstance = (src: VisibleSubsystem, hostKey: string, out: VisibleSubsystem[]) => {
    // Shallow copy: synthetic instances share the source `hosts` array by reference.
    // Downstream consumers treat these nodes read-only, so the shared reference is safe.
    const node: VisibleSubsystem = { ...src, id: nodeSeq++ };
    hostKeyById.set(node.id, hostKey);
    if (!instancesOf.has(src.id)) instancesOf.set(src.id, []);
    instancesOf.get(src.id)!.push(node);
    out.push(node);
  };

  const subsystems: VisibleSubsystem[] = [];
  for (const s of input.subsystems) {
    const hosts = s.hosts ?? [];
    if (hosts.length === 0) {
      hostMeta.set(UNASSIGNED, { name: 'Unassigned', isCurrent: false });
      addInstance(s, UNASSIGNED, subsystems);
    } else {
      for (const h of hosts) {
        const key = String(h.infrastructure_component_id);
        hostMeta.set(key, { name: h.name, isCurrent: true });
        addInstance(s, key, subsystems);
      }
    }
  }

  const externalSubsystems: VisibleSubsystem[] = [];
  for (const s of input.externalSubsystems) {
    hostMeta.set(EXTERNAL, { name: 'External', isCurrent: false });
    addInstance(s, EXTERNAL, externalSubsystems);
  }

  const fanOut = (deps: VisibleDependency[], out: VisibleDependency[]) => {
    for (const d of deps) {
      const sources = instancesOf.get(d.from_subsystem_id) ?? [];
      const targets = instancesOf.get(d.to_subsystem_id) ?? [];
      for (const src of sources) {
        for (const tgt of targets) {
          const id = edgeSeq++;
          edgeDepResolver.set(id, d.id);
          out.push({ ...d, id, from_subsystem_id: src.id, to_subsystem_id: tgt.id });
        }
      }
    }
  };

  const dependencies: VisibleDependency[] = [];
  fanOut(input.dependencies, dependencies);
  const externalDependencies: VisibleDependency[] = [];
  fanOut(input.externalDependencies, externalDependencies);

  return {
    graph: { subsystems, externalSubsystems, dependencies, externalDependencies },
    hostKeyById,
    hostMeta,
    edgeDepResolver,
  };
}
