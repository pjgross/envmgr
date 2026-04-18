import { Tooltip } from '@mui/material';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';

type Props = { hasUnacknowledged?: boolean; count?: number };

export default function ConflictIndicator({ hasUnacknowledged, count }: Props) {
  if (!hasUnacknowledged) return null;
  const label = count ? `${count} unacknowledged conflicts` : 'Unacknowledged conflicts';
  return (
    <Tooltip title={label}>
      <WarningAmberIcon color="warning" fontSize="small" />
    </Tooltip>
  );
}
