import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';
import { bookingLifecycleService } from '../services/bookingLifecycleService';

interface BookingLifecycleState {
  templates: BookingLifecycleTemplate[];
  bookingTypes: BookingTypeRecord[];
  loading: boolean;
  error: string | null;
}

const initialState: BookingLifecycleState = {
  templates: [],
  bookingTypes: [],
  loading: false,
  error: null,
};

export const fetchLifecycleTemplates = createAsyncThunk(
  'bookingLifecycle/fetchTemplates',
  () => bookingLifecycleService.listTemplates()
);

export const fetchBookingTypes = createAsyncThunk(
  'bookingLifecycle/fetchBookingTypes',
  () => bookingLifecycleService.listBookingTypes()
);

export const createLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/createTemplate',
  (data: Parameters<typeof bookingLifecycleService.createTemplate>[0]) =>
    bookingLifecycleService.createTemplate(data)
);

export const updateLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/updateTemplate',
  ({ id, data }: { id: number; data: Parameters<typeof bookingLifecycleService.updateTemplate>[1] }) =>
    bookingLifecycleService.updateTemplate(id, data)
);

export const copyLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/copyTemplate',
  ({ id, name }: { id: number; name: string }) =>
    bookingLifecycleService.copyTemplate(id, name)
);

export const createBookingType = createAsyncThunk(
  'bookingLifecycle/createBookingType',
  (data: Parameters<typeof bookingLifecycleService.createBookingType>[0]) =>
    bookingLifecycleService.createBookingType(data)
);

export const updateBookingType = createAsyncThunk(
  'bookingLifecycle/updateBookingType',
  ({ id, data }: { id: number; data: Parameters<typeof bookingLifecycleService.updateBookingType>[1] }) =>
    bookingLifecycleService.updateBookingType(id, data)
);

const bookingLifecycleSlice = createSlice({
  name: 'bookingLifecycle',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchLifecycleTemplates.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchLifecycleTemplates.fulfilled, (state, action) => {
        state.loading = false;
        state.templates = action.payload;
      })
      .addCase(fetchLifecycleTemplates.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load templates';
      })

      .addCase(fetchBookingTypes.fulfilled, (state, action) => {
        state.bookingTypes = action.payload;
      })

      .addCase(createLifecycleTemplate.fulfilled, (state, action) => {
        state.templates.push(action.payload);
      })
      .addCase(updateLifecycleTemplate.fulfilled, (state, action) => {
        const idx = state.templates.findIndex(t => t.id === action.payload.id);
        if (idx !== -1) state.templates[idx] = action.payload;
      })
      .addCase(copyLifecycleTemplate.fulfilled, (state, action) => {
        state.templates.push(action.payload);
      })
      .addCase(createBookingType.fulfilled, (state, action) => {
        state.bookingTypes.push(action.payload);
      })
      .addCase(updateBookingType.fulfilled, (state, action) => {
        const idx = state.bookingTypes.findIndex(bt => bt.id === action.payload.id);
        if (idx !== -1) state.bookingTypes[idx] = action.payload;
      });
  },
});

export default bookingLifecycleSlice.reducer;
