import { useEffect, useState } from 'react';
import {
  Box,
  Button,
  Chip,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import DeleteIcon from '@mui/icons-material/DeleteOutline';
import { Link as RouterLink } from 'react-router-dom';
import { bookingService } from '../../services/bookingService';
import type { EnvBookingSummary } from '../../types/bookingRequest';
import type { AllowedTransition } from '../../types/bookingLifecycle';
import TransitionButtons from './TransitionButtons';
import { formatBookingDateTime } from '../../utils/datetime';

type Props = {
  requestId: number;
  envBookings: EnvBookingSummary[];
  highlightBookingId?: number;
  onTransition: (bookingId: number, toState: string, label: string) => void;
  onRemove: (bookingId: number) => void;
  onAddClick: () => void;
};

export default function EnvironmentsPanel({
  requestId: _requestId,
  envBookings,
  highlightBookingId,
  onTransition,
  onRemove,
  onAddClick,
}: Props) {
  const [transitionsByBooking, setTransitionsByBooking] = useState<
    Record<number, AllowedTransition[]>
  >({});

  useEffect(() => {
    // Preload allowed transitions for each env booking on mount
    let cancelled = false;
    const load = async () => {
      const out: Record<number, AllowedTransition[]> = {};
      for (const b of envBookings) {
        out[b.id] = await bookingService.getAllowedTransitions(b.id);
      }
      if (!cancelled) setTransitionsByBooking(out);
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [envBookings]);

  return (
    <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1 }}>
          Environments
        </Typography>
        <Button size="small" onClick={onAddClick}>
          + Add Environment
        </Button>
      </Box>
      <TableContainer>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Environment</TableCell>
              <TableCell>Start</TableCell>
              <TableCell>End</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Actions</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {envBookings.map((b) => (
              <TableRow
                key={b.id}
                sx={b.id === highlightBookingId ? { bgcolor: 'action.hover' } : undefined}
              >
                <TableCell>
                  <RouterLink to={`/bookings/${b.id}`}>
                    {b.environment_name ?? `#${b.environment_id}`}
                  </RouterLink>
                </TableCell>
                <TableCell>{formatBookingDateTime(b.start_date)}</TableCell>
                <TableCell>{formatBookingDateTime(b.end_date)}</TableCell>
                <TableCell>
                  <Chip size="small" label={b.status} />
                </TableCell>
                <TableCell>
                  <TransitionButtons
                    transitions={transitionsByBooking[b.id] ?? []}
                    onTransition={(to, label) => onTransition(b.id, to, label)}
                  />
                </TableCell>
                <TableCell>
                  <IconButton size="small" onClick={() => onRemove(b.id)}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}
