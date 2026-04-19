/**
 * LinkedBookingsSection — tabular list of bookings linked to this release.
 */
import { Box, Typography } from '@mui/material';
import ReleaseBookingsTable from './ReleaseBookingsTable';
import type { BookingResponse } from '../../types/booking';
import type { TestPhaseResponse } from '../../types/release';

interface Props {
  bookings: BookingResponse[];
  phases: TestPhaseResponse[];
  loading?: boolean;
}

export default function LinkedBookingsSection({ bookings, phases, loading }: Props) {
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Linked Bookings
      </Typography>
      <ReleaseBookingsTable bookings={bookings} phases={phases} loading={loading} />
    </Box>
  );
}
