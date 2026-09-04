import { useCallback } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useStore,
  type EdgeProps,
} from 'reactflow';
import { useTheme } from '@mui/material/styles';
import { edgeLabelStyle } from '../../theme';
import { getEdgeParams } from './floatingEdgeGeometry';

/**
 * A "floating" edge that attaches to whichever border point on each node faces
 * the other node, rather than fixed left/right handles. Keeps the existing edge
 * features — arrowheads, two-way markers, selection styling and labels.
 */
export default function FloatingEdge({
  id,
  source,
  target,
  markerEnd,
  markerStart,
  style,
  label,
}: EdgeProps) {
  const theme = useTheme();
  const sourceNode = useStore(useCallback((s) => s.nodeInternals.get(source), [source]));
  const targetNode = useStore(useCallback((s) => s.nodeInternals.get(target), [target]));

  if (!sourceNode || !targetNode) return null;

  const params = getEdgeParams(sourceNode, targetNode);
  if (!params) return null;

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX: params.sx,
    sourceY: params.sy,
    sourcePosition: params.sourcePos,
    targetPosition: params.targetPos,
    targetX: params.tx,
    targetY: params.ty,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        markerStart={markerStart}
        style={style}
      />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              ...edgeLabelStyle(theme),
              padding: '0 4px',
              fontSize: 11,
              lineHeight: 1.4,
              borderRadius: 2,
              pointerEvents: 'all',
              opacity: style?.opacity,
            }}
            className="nodrag nopan"
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
