import { describe, expect, it } from 'vitest';
import { decideExternalSides } from '../externalSidePlacement';

// Current system 2 has two components: API server (id 5) on the left (x=0),
// database (id 6) on the right (x=200). Midpoint x = 100.
const currentNodeX = new Map<number, number>([
  [5, 0],
  [6, 200],
]);
const subsystemSystem = new Map<number, number>([
  [5, 2], // API server → system 2 (current)
  [6, 2], // database  → system 2 (current)
  [1, 1], // Mortgage server → system 1 (external)
  [9, 3], // some component → system 3 (external)
]);

describe('decideExternalSides', () => {
  it('places an external system on the left when it links to a left-side component', () => {
    // Mortgage (sys 1) → API server (id 5, x=0, left half)
    const sides = decideExternalSides(
      currentNodeX,
      subsystemSystem,
      [{ from_subsystem_id: 1, to_subsystem_id: 5 }],
      [1],
      2
    );
    expect(sides.get(1)).toBe('left');
  });

  it('places an external system on the right when it links to a right-side component', () => {
    // sys 3 (id 9) → database (id 6, x=200, right half)
    const sides = decideExternalSides(
      currentNodeX,
      subsystemSystem,
      [{ from_subsystem_id: 9, to_subsystem_id: 6 }],
      [3],
      2
    );
    expect(sides.get(3)).toBe('right');
  });

  it('respects direction both ways (dependency pointing into the current system)', () => {
    // API server (id 5) → Mortgage (id 1): current endpoint is still id 5 (left)
    const sides = decideExternalSides(
      currentNodeX,
      subsystemSystem,
      [{ from_subsystem_id: 5, to_subsystem_id: 1 }],
      [1],
      2
    );
    expect(sides.get(1)).toBe('left');
  });

  it('defaults to the right when an external system has no link into the current system', () => {
    const sides = decideExternalSides(currentNodeX, subsystemSystem, [], [1, 3], 2);
    expect(sides.get(1)).toBe('right');
    expect(sides.get(3)).toBe('right');
  });

  it('averages multiple connections to pick a side', () => {
    // sys 1 links to both API server (x=0) and database (x=200); avg=100=mid → right
    const sides = decideExternalSides(
      currentNodeX,
      subsystemSystem,
      [
        { from_subsystem_id: 1, to_subsystem_id: 5 },
        { from_subsystem_id: 1, to_subsystem_id: 6 },
      ],
      [1],
      2
    );
    expect(sides.get(1)).toBe('right'); // avg not strictly less than midpoint
  });
});
