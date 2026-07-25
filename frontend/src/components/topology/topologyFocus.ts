export interface FocusDep {
  id: number;
  from_subsystem_id: number;
  to_subsystem_id: number;
}

export interface FocusSet {
  nodeIds: Set<string>;
  edgeIds: Set<string>;
}

/** Focused component + everything directly linked to/from it, and the incident edges. */
export function computeFocusSet(focusedId: string, dependencies: FocusDep[]): FocusSet {
  const nodeIds = new Set<string>([focusedId]);
  const edgeIds = new Set<string>();
  for (const d of dependencies) {
    const from = String(d.from_subsystem_id);
    const to = String(d.to_subsystem_id);
    if (from === focusedId) {
      nodeIds.add(to);
      edgeIds.add(String(d.id));
    } else if (to === focusedId) {
      nodeIds.add(from);
      edgeIds.add(String(d.id));
    }
  }
  return { nodeIds, edgeIds };
}

export interface SearchableComponent {
  id: number;
  name: string;
  systemName: string;
}

/** Case-insensitive substring match on component name; empty/whitespace query → []. */
export function matchComponents(
  query: string,
  components: SearchableComponent[]
): SearchableComponent[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return components.filter((c) => c.name.toLowerCase().includes(q));
}
