import { describe, expect, it } from 'vitest';
import { Position } from 'reactflow';
import { getEdgeParams, type FloatingNodeLike } from '../floatingEdgeGeometry';

const node = (x: number, y: number): FloatingNodeLike => ({
  position: { x, y },
  positionAbsolute: { x, y },
  width: 100,
  height: 40,
});

describe('getEdgeParams', () => {
  it('returns null when a node has not been measured yet', () => {
    const unmeasured: FloatingNodeLike = { position: { x: 0, y: 0 } };
    expect(getEdgeParams(unmeasured, node(300, 0))).toBeNull();
  });

  it('exits the right and enters the left when the source is left of the target', () => {
    const params = getEdgeParams(node(0, 0), node(300, 0));
    expect(params).not.toBeNull();
    expect(params!.sourcePos).toBe(Position.Right);
    expect(params!.targetPos).toBe(Position.Left);
  });

  it('exits the left and enters the right when the source is right of the target (the bug case)', () => {
    // Source at x=300, target at x=0 → the edge should NOT loop back across the
    // middle; it should leave the source's left and enter the target's right.
    const params = getEdgeParams(node(300, 0), node(0, 0));
    expect(params).not.toBeNull();
    expect(params!.sourcePos).toBe(Position.Left);
    expect(params!.targetPos).toBe(Position.Right);
  });

  it('attaches near the facing border, not the far side', () => {
    // Source left of target: source attach point is near its right edge (x≈100),
    // target attach point near its left edge (x≈300).
    const params = getEdgeParams(node(0, 0), node(300, 0))!;
    expect(params.sx).toBeGreaterThan(90);
    expect(params.tx).toBeLessThan(310);
  });

  it('uses top/bottom sides when nodes are stacked vertically', () => {
    const params = getEdgeParams(node(0, 0), node(0, 300))!;
    expect(params.sourcePos).toBe(Position.Bottom);
    expect(params.targetPos).toBe(Position.Top);
  });
});
