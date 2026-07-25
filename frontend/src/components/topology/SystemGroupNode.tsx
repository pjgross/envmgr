import { Box, IconButton, Typography } from '@mui/material';
import UnfoldLessIcon from '@mui/icons-material/UnfoldLess';

interface SystemGroupNodeProps {
  data: {
    label: string;
    isCurrent: boolean;
    dimmed?: boolean;
    systemId?: number;
    onCollapse?: (systemId: number) => void;
  };
}

export default function SystemGroupNode({ data }: SystemGroupNodeProps) {
  const borderColor = data.isCurrent ? '#1976d2' : '#9e9e9e';
  const bgColor = data.isCurrent ? 'rgba(25,118,210,0.03)' : 'rgba(158,158,158,0.03)';
  const labelColor = data.isCurrent ? '#1976d2' : '#757575';

  return (
    <Box
      sx={{
        width: '100%',
        height: '100%',
        border: `2px dashed ${borderColor}`,
        borderRadius: 2,
        bgcolor: bgColor,
        position: 'relative',
        pointerEvents: 'none',
        opacity: data.dimmed ? 0.3 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          top: -11,
          left: 14,
          bgcolor: 'background.default',
          px: 0.75,
          lineHeight: 1,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <Typography
          variant="caption"
          sx={{
            fontWeight: 700,
            color: labelColor,
            fontSize: '0.7rem',
            letterSpacing: 0.4,
            textTransform: 'uppercase',
          }}
        >
          {data.label}
        </Typography>
        {data.onCollapse && data.systemId !== undefined && (
          <IconButton
            size="small"
            aria-label={`Collapse ${data.label}`}
            onClick={(e) => {
              e.stopPropagation();
              data.onCollapse!(data.systemId!);
            }}
            sx={{ p: 0.25, ml: 0.5, pointerEvents: 'auto' }}
          >
            <UnfoldLessIcon sx={{ fontSize: 16, transform: 'rotate(90deg)' }} />
          </IconButton>
        )}
      </Box>
    </Box>
  );
}
