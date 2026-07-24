import { describe, expect, it } from 'vitest';
import { positionColumns, type GroupBox } from '../topologyColumnLayout';

const box = (id: number, width = 200, height = 100): GroupBox => ({ id, width, height });

describe('positionColumns', () => {
  it('stacks two left-column systems vertically at the same x, not in a row', () => {
    const origins = positionColumns([box(1), box(3)], box(2), [], 40);
    const a = origins.get(1)!;
    const b = origins.get(3)!;
    expect(a.x).toBe(b.x); // same column → same x
    expect(b.y).toBeGreaterThan(a.y); // stacked vertically
    expect(b.y - a.y).toBe(100 + 40); // height + gap
  });

  it('places the current system to the right of the left column', () => {
    const origins = positionColumns([box(1), box(3)], box(2), [], 40);
    const left = origins.get(1)!;
    const current = origins.get(2)!;
    expect(current.x).toBeGreaterThan(left.x + 200); // clear of the left column + gap
  });

  it('places right-column systems to the right of the current system', () => {
    const origins = positionColumns([], box(2), [box(4), box(5)], 40);
    const current = origins.get(2)!;
    const right = origins.get(4)!;
    expect(right.x).toBeGreaterThan(current.x + 200);
    expect(origins.get(5)!.y).toBeGreaterThan(origins.get(4)!.y); // stacked
  });

  it('vertically centres a short column against a taller one', () => {
    // Left column has two boxes (tall), current has one (short) → current offset down.
    const origins = positionColumns([box(1), box(3)], box(2), [], 40);
    expect(origins.get(2)!.y).toBeGreaterThan(0);
  });

  it('starts the current system at x=0 when there are no left externals', () => {
    const origins = positionColumns([], box(2), [box(4)], 40);
    expect(origins.get(2)!.x).toBe(0);
  });
});
