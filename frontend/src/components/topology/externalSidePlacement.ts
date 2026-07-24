/**
 * Decide which side of the current system each external system should be placed
 * on, so that an external system sits next to the component it links to rather
 * than always being appended to the right.
 *
 * For each external system we look at the dependencies connecting it to the
 * current system, take the average horizontal position of the current-system
 * components involved, and compare that to the midpoint of the current group:
 * links into the left half → place the external system on the left; otherwise
 * on the right. External systems with no link into the current system default
 * to the right (unchanged behaviour).
 */

export type Side = 'left' | 'right';

export interface DependencyEndpoints {
  from_subsystem_id: number;
  to_subsystem_id: number;
}

export function decideExternalSides(
  /** current-system component id → its horizontal position in the group layout */
  currentNodeX: Map<number, number>,
  /** every subsystem id → the system it belongs to */
  subsystemSystem: Map<number, number>,
  dependencies: DependencyEndpoints[],
  externalSystemIds: number[],
  currentSystemId: number
): Map<number, Side> {
  const xs = [...currentNodeX.values()];
  const midX = xs.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0;

  const result = new Map<number, Side>();
  for (const extId of externalSystemIds) {
    const connectedX: number[] = [];
    for (const d of dependencies) {
      const fromSys = subsystemSystem.get(d.from_subsystem_id);
      const toSys = subsystemSystem.get(d.to_subsystem_id);
      if (fromSys === currentSystemId && toSys === extId) {
        const x = currentNodeX.get(d.from_subsystem_id);
        if (x !== undefined) connectedX.push(x);
      } else if (toSys === currentSystemId && fromSys === extId) {
        const x = currentNodeX.get(d.to_subsystem_id);
        if (x !== undefined) connectedX.push(x);
      }
    }

    if (connectedX.length === 0) {
      result.set(extId, 'right');
    } else {
      const avg = connectedX.reduce((a, b) => a + b, 0) / connectedX.length;
      result.set(extId, avg < midX ? 'left' : 'right');
    }
  }
  return result;
}
