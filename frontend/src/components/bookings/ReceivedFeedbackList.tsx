import { Box, Link, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import type { ReceivedFeedbackItem } from '../../types/conflict';
import { formatBookingDateTime } from '../../utils/datetime';

type Props = {
  items: ReceivedFeedbackItem[];
};

function willingLabel(v: boolean | null): string {
  if (v === true) return 'Yes';
  if (v === false) return 'No';
  return '(not yet answered)';
}

export default function ReceivedFeedbackList({ items }: Props) {
  if (items.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
        No feedback received yet.
      </Typography>
    );
  }

  return (
    <Box>
      {items.map((it, idx) => (
        <Box
          key={`${it.source_booking.id}-${it.acknowledged_at}`}
          sx={{
            mb: 2,
            pb: 2,
            borderBottom: idx === items.length - 1 ? 'none' : '1px solid',
            borderColor: 'divider',
          }}
        >
          <Typography variant="body2">
            <Link
              component={RouterLink}
              to={`/bookings/${it.source_booking.id}`}
              sx={{ fontWeight: 'medium' }}
            >
              {it.source_request.project_name ??
                it.source_booking.project_name ??
                `Booking #${it.source_booking.id}`}
            </Link>
            {it.source_booking.environment_name
              ? ` · ${it.source_booking.environment_name}`
              : ''}
            {' · '}
            {formatBookingDateTime(it.source_booking.start_date)} –{' '}
            {formatBookingDateTime(it.source_booking.end_date)}
            {' · '}status {it.source_booking.status}
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.5 }}>
            Booked by: {it.source_request.booked_by.username} ({it.source_request.booked_by.email})
          </Typography>
          <Typography variant="body2" sx={{ mt: 1 }}>
            Willing to share: <strong>{willingLabel(it.willing_to_share)}</strong>
          </Typography>
          {it.notes && (
            <Typography variant="body2" sx={{ mt: 0.5, whiteSpace: 'pre-wrap' }}>
              "{it.notes}"
            </Typography>
          )}
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            — {it.acknowledged_by.username}, {new Date(it.acknowledged_at).toLocaleString()}
          </Typography>
        </Box>
      ))}
    </Box>
  );
}
