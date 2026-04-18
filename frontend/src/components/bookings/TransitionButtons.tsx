import { Box, Button } from '@mui/material';
import type { AllowedTransition } from '../../types/bookingLifecycle';

type Props = {
  transitions: AllowedTransition[];
  onTransition: (toState: string, label: string) => void;
  size?: 'small' | 'medium';
};

export default function TransitionButtons({ transitions, onTransition, size = 'small' }: Props) {
  if (transitions.length === 0) return null;
  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
      {transitions.map((t) => (
        <Button
          key={t.to_state}
          variant="contained"
          color={
            t.to_state === 'rejected' ? 'error' : t.to_state === 'approved' ? 'success' : 'primary'
          }
          size={size}
          onClick={() => onTransition(t.to_state, t.label)}
        >
          {t.label}
        </Button>
      ))}
    </Box>
  );
}
