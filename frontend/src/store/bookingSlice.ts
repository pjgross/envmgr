import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { bookingService } from '../services/bookingService';
import type { BookingResponse, BookingCreate } from '../types/booking';
import type { ConflictItem } from '../types/conflict';

interface BookingState {
  bookings: BookingResponse[];
  total: number;
  selectedBooking: BookingResponse | null;
  loading: boolean;
  /**
   * The list query's own flag. `loading` is shared by the other thunks, and
   * an aborted list request on unmount has no successor to clear it —
   * isolating the list keeps that from hanging every other consumer of the
   * slice.
   */
  listLoading: boolean;
  error: string | null;
  overlapWarnings: number[];
  conflicts: Record<number, ConflictItem[]>;
}

const initialState: BookingState = {
  bookings: [],
  total: 0,
  selectedBooking: null,
  loading: false,
  listLoading: false,
  error: null,
  overlapWarnings: [],
  conflicts: {},
};

export const fetchBookings = createAsyncThunk(
  'booking/fetchBookings',
  (params?: {
    environment_id?: number;
    start?: string;
    end?: string;
    booking_status?: string;
    limit?: number;
    offset?: number;
    sort_by?: string;
    sort_dir?: 'asc' | 'desc';
  }) => bookingService.listBookings(params)
);

export const createBooking = createAsyncThunk('booking/createBooking', (data: BookingCreate) =>
  bookingService.createBooking(data)
);

export const getBooking = createAsyncThunk('booking/getBooking', (id: number) =>
  bookingService.getBooking(id)
);

export const deleteOccurrence = createAsyncThunk('booking/deleteOccurrence', async (id: number) => {
  await bookingService.deleteOccurrence(id);
  return id;
});

export const deleteSeries = createAsyncThunk('booking/deleteSeries', async (id: number) => {
  await bookingService.deleteSeries(id);
  return id;
});

export const fetchConflicts = createAsyncThunk('booking/fetchConflicts', async (id: number) => {
  const conflicts = await bookingService.getConflicts(id);
  return { bookingId: id, conflicts };
});

export const acknowledgeConflict = createAsyncThunk(
  'booking/ackConflict',
  async (args: { id: number; otherId: number; willing_to_share: boolean; notes?: string }) => {
    const ack = await bookingService.acknowledgeConflict(args.id, args.otherId, {
      willing_to_share: args.willing_to_share,
      notes: args.notes,
    });
    return { bookingId: args.id, otherId: args.otherId, ack };
  }
);

const bookingSlice = createSlice({
  name: 'booking',
  initialState,
  reducers: {
    clearOverlapWarnings: (state) => {
      state.overlapWarnings = [];
    },
    clearSelectedBooking: (state) => {
      state.selectedBooking = null;
    },
  },
  extraReducers: (builder) => {
    builder
      // fetchBookings
      .addCase(fetchBookings.pending, (state) => {
        state.listLoading = true;
        state.error = null;
      })
      .addCase(fetchBookings.fulfilled, (state, action) => {
        state.bookings = action.payload.rows;
        state.total = action.payload.total;
        state.listLoading = false;
      })
      .addCase(fetchBookings.rejected, (state, action) => {
        // useServerGrid aborts a superseded request rather than ignoring its
        // reply. RTK dispatches `pending` for the new request synchronously,
        // then `rejected` for the aborted one on a microtask — without this
        // guard the spinner flickers off and `error` is set to 'Aborted'
        // while the real request is still in flight.
        if (action.meta.aborted) return;
        state.listLoading = false;
        state.error = action.error.message ?? 'Failed to fetch bookings';
      })
      // createBooking
      .addCase(createBooking.pending, (state) => {
        state.loading = true;
        state.error = null;
        state.overlapWarnings = [];
      })
      .addCase(createBooking.fulfilled, (state, action) => {
        state.bookings.push(action.payload.booking);
        state.overlapWarnings = action.payload.overlap_warnings;
        state.loading = false;
      })
      .addCase(createBooking.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to create booking';
      })
      // getBooking
      .addCase(getBooking.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(getBooking.fulfilled, (state, action) => {
        state.selectedBooking = action.payload;
        state.loading = false;
      })
      .addCase(getBooking.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to fetch booking';
      })
      // deleteOccurrence
      .addCase(deleteOccurrence.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(deleteOccurrence.fulfilled, (state, action) => {
        state.bookings = state.bookings.filter((b) => b.id !== action.payload);
        if (state.selectedBooking?.id === action.payload) state.selectedBooking = null;
        state.loading = false;
      })
      .addCase(deleteOccurrence.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete occurrence';
      })
      // deleteSeries
      .addCase(deleteSeries.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(deleteSeries.fulfilled, (state, action) => {
        // Remove the deleted booking and all its children from local state
        const deletedId = action.payload;
        state.bookings = state.bookings.filter(
          (b) => b.id !== deletedId && b.recurrence_parent_id !== deletedId
        );
        if (state.selectedBooking?.id === deletedId) state.selectedBooking = null;
        state.loading = false;
      })
      .addCase(deleteSeries.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to delete series';
      })
      // fetchConflicts
      .addCase(fetchConflicts.fulfilled, (state, action) => {
        state.conflicts[action.payload.bookingId] = action.payload.conflicts;
      })
      .addCase(fetchConflicts.rejected, (state, action) => {
        state.error = action.error.message ?? 'Failed to fetch conflicts';
      })
      // acknowledgeConflict
      .addCase(acknowledgeConflict.fulfilled, (state, action) => {
        const { bookingId, otherId, ack } = action.payload;
        const items = state.conflicts[bookingId];
        if (items) {
          const item = items.find((c) => c.other_booking.id === otherId);
          if (item) item.ack = ack;
        }
      })
      .addCase(acknowledgeConflict.rejected, (state, action) => {
        state.error = action.error.message ?? 'Failed to acknowledge conflict';
      });
  },
});

export const { clearOverlapWarnings, clearSelectedBooking } = bookingSlice.actions;
export default bookingSlice.reducer;
