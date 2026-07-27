/**
 * ReleaseEnvironmentsTab — environment resource Gantt + bookings table.
 */
import { useCallback, useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Box, Button, Divider, Typography } from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import { AppDispatch, RootState } from '../../store';
import { fetchPhases } from '../../store/releaseSlice';
import { releaseService } from '../../services/releaseService';
import EnvironmentResourceGantt from './EnvironmentResourceGantt';
import ReleaseBookingsTable from './ReleaseBookingsTable';
import AddPhaseBookingDialog from './AddPhaseBookingDialog';
import ReleaseEnvironmentCoverage from './ReleaseEnvironmentCoverage';
import BulkBookEnvironmentsDialog from './BulkBookEnvironmentsDialog';
import type { BookingResponse } from '../../types/booking';

interface Props {
  releaseId: number;
}

export default function ReleaseEnvironmentsTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const phases = useSelector((s: RootState) => s.release.phases);

  const [bookings, setBookings] = useState<BookingResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [bookEnvId, setBookEnvId] = useState<number | undefined>(undefined);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkEnvIds, setBulkEnvIds] = useState<number[]>([]);

  const loadBookings = useCallback(async () => {
    setLoading(true);
    try {
      const data = await releaseService.listBookings(releaseId);
      setBookings(data);
    } catch {
      setBookings([]);
    } finally {
      setLoading(false);
    }
  }, [releaseId]);

  useEffect(() => {
    dispatch(fetchPhases(releaseId));
    loadBookings();
  }, [dispatch, releaseId, loadBookings]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <ReleaseEnvironmentCoverage
        releaseId={releaseId}
        onBook={(environmentId) => {
          setBookEnvId(environmentId);
          setAddOpen(true);
        }}
        onBookMany={(environmentIds) => {
          setBulkEnvIds(environmentIds);
          setBulkOpen(true);
        }}
      />

      <Divider />

      <Box>
        <Typography variant="subtitle1" fontWeight="medium" sx={{ mb: 1 }}>
          Environment Timeline
        </Typography>
        <EnvironmentResourceGantt bookings={bookings} phases={phases} />
      </Box>

      <Divider />

      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="subtitle1" fontWeight="medium">
            Bookings
          </Typography>
          <Button
            size="small"
            startIcon={<AddIcon />}
            onClick={() => {
              setBookEnvId(undefined);
              setAddOpen(true);
            }}
          >
            Add Booking
          </Button>
        </Box>
        <ReleaseBookingsTable bookings={bookings} phases={phases} loading={loading} />
      </Box>

      <AddPhaseBookingDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        releaseId={releaseId}
        phases={phases}
        onCreated={loadBookings}
        initialEnvironmentId={bookEnvId}
      />
      <BulkBookEnvironmentsDialog
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        releaseId={releaseId}
        environmentIds={bulkEnvIds}
        phases={phases}
        onCreated={loadBookings}
      />
    </Box>
  );
}
