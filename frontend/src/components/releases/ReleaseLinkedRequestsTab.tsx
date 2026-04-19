/**
 * ReleaseLinkedRequestsTab — bookings + change requests linked to this release.
 */
import { useCallback, useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { Box, Button, Divider } from '@mui/material';
import AddLinkIcon from '@mui/icons-material/AddLink';
import { AppDispatch, RootState } from '../../store';
import { fetchPhases } from '../../store/releaseSlice';
import { releaseService } from '../../services/releaseService';
import LinkedBookingsSection from './LinkedBookingsSection';
import LinkedChangeRequestsSection from './LinkedChangeRequestsSection';
import LinkChangeRequestDialog from './LinkChangeRequestDialog';
import type { BookingResponse } from '../../types/booking';
import type { ChangeRequestResponse } from '../../types/changeRequest';

interface Props {
  releaseId: number;
}

export default function ReleaseLinkedRequestsTab({ releaseId }: Props) {
  const dispatch = useDispatch<AppDispatch>();
  const phases = useSelector((s: RootState) => s.release.phases);

  const [bookings, setBookings] = useState<BookingResponse[]>([]);
  const [changeRequests, setCRs] = useState<ChangeRequestResponse[]>([]);
  const [loadingBookings, setLoadingBookings] = useState(false);
  const [loadingCRs, setLoadingCRs] = useState(false);
  const [linkDialogOpen, setLinkDialogOpen] = useState(false);

  const loadBookings = useCallback(async () => {
    setLoadingBookings(true);
    try {
      setBookings(await releaseService.listBookings(releaseId));
    } catch {
      setBookings([]);
    } finally {
      setLoadingBookings(false);
    }
  }, [releaseId]);

  const loadCRs = useCallback(async () => {
    setLoadingCRs(true);
    try {
      setCRs(await releaseService.listLinkedChangeRequests(releaseId));
    } catch {
      setCRs([]);
    } finally {
      setLoadingCRs(false);
    }
  }, [releaseId]);

  useEffect(() => {
    dispatch(fetchPhases(releaseId));
    loadBookings();
    loadCRs();
  }, [dispatch, releaseId, loadBookings, loadCRs]);

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <LinkedBookingsSection
        bookings={bookings}
        phases={phases}
        loading={loadingBookings}
      />

      <Divider />

      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1 }}>
          <Button
            size="small"
            startIcon={<AddLinkIcon />}
            onClick={() => setLinkDialogOpen(true)}
          >
            Link CR
          </Button>
        </Box>
        <LinkedChangeRequestsSection
          releaseId={releaseId}
          changeRequests={changeRequests}
          loading={loadingCRs}
          onUnlinked={loadCRs}
        />
      </Box>

      <LinkChangeRequestDialog
        open={linkDialogOpen}
        onClose={() => setLinkDialogOpen(false)}
        releaseId={releaseId}
        onLinked={loadCRs}
      />
    </Box>
  );
}
