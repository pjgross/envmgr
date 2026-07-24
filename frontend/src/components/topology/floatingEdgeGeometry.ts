import { Position } from 'reactflow';

/**
 * Geometry for React Flow "floating" edges: instead of pinning every edge to a
 * fixed handle (source-right / target-left), compute the point on each node's
 * border that faces the other node, and which side that point sits on. This
 * lets an edge exit/enter whichever side is nearest, so a link never has to
 * loop back across the middle of the diagram when the target is to the left of
 * the source.
 *
 * Adapted from the React Flow floating-edges example, hardened against
 * not-yet-measured nodes (undefined width/height/positionAbsolute).
 */

export interface FloatingNodeLike {
  position: { x: number; y: number };
  positionAbsolute?: { x: number; y: number };
  width?: number | null;
  height?: number | null;
}

interface Point {
  x: number;
  y: number;
}

function absPosition(node: FloatingNodeLike): Point {
  return node.positionAbsolute ?? node.position;
}

/**
 * Point where a straight line from `target`'s centre to `node`'s centre crosses
 * `node`'s border (treating the node as a rectangle).
 */
export function getNodeIntersection(
  node: FloatingNodeLike,
  target: FloatingNodeLike
): Point {
  const w = (node.width ?? 0) / 2;
  const h = (node.height ?? 0) / 2;
  const nodePos = absPosition(node);
  const targetPos = absPosition(target);

  const x2 = nodePos.x + w;
  const y2 = nodePos.y + h;
  const x1 = targetPos.x + (target.width ?? 0) / 2;
  const y1 = targetPos.y + (target.height ?? 0) / 2;

  const xx1 = (x1 - x2) / (2 * w) - (y1 - y2) / (2 * h);
  const yy1 = (x1 - x2) / (2 * w) + (y1 - y2) / (2 * h);
  const a = 1 / (Math.abs(xx1) + Math.abs(yy1));
  const xx3 = a * xx1;
  const yy3 = a * yy1;
  const x = w * (xx3 + yy3) + x2;
  const y = h * (-xx3 + yy3) + y2;

  return { x, y };
}

/** Which side of `node` the given border point sits on. */
export function getEdgePosition(node: FloatingNodeLike, point: Point): Position {
  const pos = absPosition(node);
  const nx = Math.round(pos.x);
  const ny = Math.round(pos.y);
  const px = Math.round(point.x);
  const py = Math.round(point.y);

  if (px <= nx + 1) return Position.Left;
  if (px >= nx + (node.width ?? 0) - 1) return Position.Right;
  if (py <= ny + 1) return Position.Top;
  if (py >= ny + (node.height ?? 0) - 1) return Position.Bottom;
  return Position.Top;
}

export interface EdgeParams {
  sx: number;
  sy: number;
  tx: number;
  ty: number;
  sourcePos: Position;
  targetPos: Position;
}

/**
 * Border-attachment points and sides for an edge between two nodes. Returns
 * null when either node has not been measured yet (no dimensions), so the edge
 * can be skipped for that frame rather than drawn with NaN coordinates.
 */
export function getEdgeParams(
  source: FloatingNodeLike,
  target: FloatingNodeLike
): EdgeParams | null {
  if (!source.width || !source.height || !target.width || !target.height) {
    return null;
  }
  const sourceIntersection = getNodeIntersection(source, target);
  const targetIntersection = getNodeIntersection(target, source);
  return {
    sx: sourceIntersection.x,
    sy: sourceIntersection.y,
    tx: targetIntersection.x,
    ty: targetIntersection.y,
    sourcePos: getEdgePosition(source, sourceIntersection),
    targetPos: getEdgePosition(target, targetIntersection),
  };
}
