import { Box, Typography } from '@mui/material';

interface SystemGroupNodeProps {
  data: { label: string; isCurrent: boolean };
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
      </Box>
    </Box>
  );
}
