import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { bookingService } from '../services/bookingService';
import type { BookingResponse, BookingCreate } from '../types/booking';

interface BookingState {
  bookings: BookingResponse[];
  selectedBooking: BookingResponse | null;
  loading: boolean;
  error: string | null;
  overlapWarnings: number[];
}

const initialState: BookingState = {
  bookings: [],
  selectedBooking: null,
  loading: false,
  error: null,
  overlapWarnings: [],
};

export const fetchBookings = createAsyncThunk(
  'booking/fetchBookings',
  (params?: { environment_id?: number; start?: string; end?: string; booking_status?: string }) =>
    bookingService.listBookings(params)
);

export const createBooking = createAsyncThunk(
  'booking/createBooking',
  (data: BookingCreate) => bookingService.createBooking(data)
);

export const getBooking = createAsyncThunk('booking/getBooking', (id: number) =>
  bookingService.getBooking(id)
);

export const approveBooking = createAsyncThunk('booking/approveBooking', (id: number) =>
  bookingService.approveBooking(id)
);

export const rejectBooking = createAsyncThunk('booking/rejectBooking', (id: number) =>
  bookingService.rejectBooking(id)
);

export const cancelBooking = createAsyncThunk('booking/cancelBooking', async (id: number) => {
  await bookingService.cancelBooking(id);
  return id;
});

export const deleteOccurrence = createAsyncThunk(
  'booking/deleteOccurrence',
  async (id: number) => {
    await bookingService.deleteOccurrence(id);
    return id;
  }
);

export const deleteSeries = createAsyncThunk('booking/deleteSeries', async (id: number) => {
  await bookingService.deleteSeries(id);
  return id;
});

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
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchBookings.fulfilled, (state, action) => {
        state.bookings = action.payload;
        state.loading = false;
      })
      .addCase(fetchBookings.rejected, (state, action) => {
        state.loading = false;
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
      // approveBooking
      .addCase(approveBooking.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(approveBooking.fulfilled, (state, action) => {
        const idx = state.bookings.findIndex((b) => b.id === action.payload.id);
        if (idx !== -1) state.bookings[idx] = action.payload;
        if (state.selectedBooking?.id === action.payload.id) {
          state.selectedBooking = action.payload;
        }
        state.loading = false;
      })
      .addCase(approveBooking.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to approve booking';
      })
      // rejectBooking
      .addCase(rejectBooking.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(rejectBooking.fulfilled, (state, action) => {
        const idx = state.bookings.findIndex((b) => b.id === action.payload.id);
        if (idx !== -1) state.bookings[idx] = action.payload;
        if (state.selectedBooking?.id === action.payload.id) {
          state.selectedBooking = action.payload;
        }
        state.loading = false;
      })
      .addCase(rejectBooking.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to reject booking';
      })
      // cancelBooking
      .addCase(cancelBooking.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(cancelBooking.fulfilled, (state, action) => {
        state.bookings = state.bookings.filter((b) => b.id !== action.payload);
        if (state.selectedBooking?.id === action.payload) state.selectedBooking = null;
        state.loading = false;
      })
      .addCase(cancelBooking.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to cancel booking';
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
      });
  },
});

export const { clearOverlapWarnings, clearSelectedBooking } = bookingSlice.actions;
export default bookingSlice.reducer;
