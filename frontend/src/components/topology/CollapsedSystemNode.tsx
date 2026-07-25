import { memo } from 'react';
import { Box, Typography } from '@mui/material';
import UnfoldMoreIcon from '@mui/icons-material/UnfoldMore';
import { Handle, Position } from 'reactflow';
import { useRenderCount } from './topologyPerf';

interface CollapsedSystemNodeProps {
  data: {
    groupId: string;
    name: string;
    componentCount: number;
    isCurrent: boolean;
    dimmed?: boolean;
    onExpand?: (groupId: string) => void;
  };
}

const NODE_WIDTH = 180;
const NODE_HEIGHT = 70;

function CollapsedSystemNode({ data }: CollapsedSystemNodeProps) {
  useRenderCount('CollapsedSystemNode');
  const borderColor = data.isCurrent ? '#1976d2' : '#757575';
  return (
    <Box
      onClick={() => data.onExpand?.(data.groupId)}
      role="button"
      tabIndex={0}
      aria-label={`Expand ${data.name}`}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          data.onExpand?.(data.groupId);
        }
      }}
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px solid ${borderColor}`,
        borderRadius: 1,
        bgcolor: 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: data.onExpand ? 'pointer' : 'default',
        opacity: data.dimmed ? 0.25 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {data.name}
      </Typography>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, color: 'text.secondary' }}>
        <UnfoldMoreIcon sx={{ fontSize: 14, transform: 'rotate(90deg)' }} />
        <Typography variant="caption">
          {data.componentCount} component{data.componentCount === 1 ? '' : 's'}
        </Typography>
      </Box>
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

export default memo(CollapsedSystemNode);
