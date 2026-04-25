import { Chip } from '@mui/material';
import type { DeploymentStatus } from '../../types/deployment';

const COLORS: Record<DeploymentStatus, string> = {
  pending: '#607d8b',
  in_progress: '#607d8b',
  success: '#43a047',
  failed: '#e53935',
  rolled_back: '#ffb300',
};

const LABELS: Record<DeploymentStatus, string> = {
  pending: 'Pending',
  in_progress: 'In progress',
  success: 'Success',
  failed: 'Failed',
  rolled_back: 'Rolled back',
};

interface Props {
  status: DeploymentStatus;
  size?: 'small' | 'medium';
}

export default function DeploymentStatusChip({ status, size = 'small' }: Props) {
  return (
    <Chip
      label={LABELS[status]}
      size={size}
      sx={{ backgroundColor: COLORS[status], color: 'white', fontWeight: 500 }}
    />
  );
}
