import { memo } from 'react';
import { Box, Chip, Typography } from '@mui/material';
import { Handle, Position } from 'reactflow';
import type { RenderSubsystem } from './topologyElkGraph';
import { MOCK_COLOR } from './topologyColors';
import { useRenderCount } from './topologyPerf';

export const NODE_WIDTH = 180;
export const NODE_HEIGHT = 70;

interface SubsystemNodeProps {
  data: { label: RenderSubsystem; color: string; dimmed?: boolean };
}

function SubsystemNode({ data }: SubsystemNodeProps) {
  useRenderCount('SubsystemNode');
  const s = data.label;
  const mocked = s.is_mocked ?? false;
  const color = mocked ? MOCK_COLOR : data.color;
  return (
    <Box
      sx={{
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        border: `2px ${mocked ? 'dashed' : 'solid'} ${color}`,
        borderRadius: 1,
        bgcolor: mocked ? 'rgba(158,158,158,0.06)' : 'background.paper',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        px: 1,
        cursor: 'pointer',
        opacity: data.dimmed ? 0.25 : mocked ? 0.75 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Typography variant="body2" fontWeight="bold" noWrap sx={{ width: '100%', textAlign: 'center' }}>
        {s.name}
      </Typography>
      <Chip
        label={s.component_type.replace(/_/g, ' ')}
        size="small"
        sx={{ bgcolor: color, color: '#fff', fontSize: '0.65rem', height: 18, mt: 0.5 }}
      />
      {s.technology && (
        <Typography variant="caption" color="text.secondary" noWrap>
          {s.technology}
        </Typography>
      )}
      {mocked && (
        <Typography variant="caption" sx={{ color: MOCK_COLOR, fontSize: '0.6rem' }}>
          mocked
        </Typography>
      )}
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </Box>
  );
}

export default memo(SubsystemNode);
