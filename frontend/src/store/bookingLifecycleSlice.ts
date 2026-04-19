import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type { BookingLifecycleTemplate, BookingTypeRecord } from '../types/bookingLifecycle';
import type { EntityType } from '../types/customField';
import { bookingLifecycleService } from '../services/bookingLifecycleService';

// State keyed by entity_type so the same slice holds bookings, change requests,
// and (later) releases. Selectors below provide back-compat for callers that
// want just the booking templates.
interface BookingLifecycleState {
  templatesByEntity: Partial<Record<EntityType, BookingLifecycleTemplate[]>>;
  bookingTypes: BookingTypeRecord[];
  loading: boolean;
  error: string | null;
}

const initialState: BookingLifecycleState = {
  templatesByEntity: {},
  bookingTypes: [],
  loading: false,
  error: null,
};

export const fetchLifecycleTemplates = createAsyncThunk(
  'bookingLifecycle/fetchTemplates',
  async (entityType: EntityType = 'booking') => ({
    entityType,
    templates: await bookingLifecycleService.listTemplates(entityType),
  })
);

export const fetchBookingTypes = createAsyncThunk('bookingLifecycle/fetchBookingTypes', () =>
  bookingLifecycleService.listBookingTypes()
);

export const createLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/createTemplate',
  async ({
    data,
    entityType = 'booking',
  }: {
    data: Parameters<typeof bookingLifecycleService.createTemplate>[0];
    entityType?: EntityType;
  }) => bookingLifecycleService.createTemplate(data, entityType)
);

export const updateLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/updateTemplate',
  ({
    id,
    data,
  }: {
    id: number;
    data: Parameters<typeof bookingLifecycleService.updateTemplate>[1];
  }) => bookingLifecycleService.updateTemplate(id, data)
);

export const copyLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/copyTemplate',
  ({ id, name }: { id: number; name: string }) => bookingLifecycleService.copyTemplate(id, name)
);

export const createBookingType = createAsyncThunk(
  'bookingLifecycle/createBookingType',
  (data: Parameters<typeof bookingLifecycleService.createBookingType>[0]) =>
    bookingLifecycleService.createBookingType(data)
);

export const updateBookingType = createAsyncThunk(
  'bookingLifecycle/updateBookingType',
  ({
    id,
    data,
  }: {
    id: number;
    data: Parameters<typeof bookingLifecycleService.updateBookingType>[1];
  }) => bookingLifecycleService.updateBookingType(id, data)
);

export const deleteLifecycleTemplate = createAsyncThunk(
  'bookingLifecycle/deleteTemplate',
  (id: number) => bookingLifecycleService.deleteTemplate(id).then(() => id)
);

export const deleteBookingType = createAsyncThunk(
  'bookingLifecycle/deleteBookingType',
  (id: number) => bookingLifecycleService.deleteBookingType(id).then(() => id)
);

/** Helper: locate the entity_type a given template id belongs to in state. */
function findEntityTypeOf(
  byEntity: Partial<Record<EntityType, BookingLifecycleTemplate[]>>,
  templateId: number
): EntityType | null {
  for (const [et, list] of Object.entries(byEntity) as [EntityType, BookingLifecycleTemplate[]][]) {
    if (list?.some((t) => t.id === templateId)) return et;
  }
  return null;
}

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
        state.templatesByEntity[action.payload.entityType] = action.payload.templates;
      })
      .addCase(fetchLifecycleTemplates.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load templates';
      })

      .addCase(fetchBookingTypes.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchBookingTypes.fulfilled, (state, action) => {
        state.loading = false;
        state.bookingTypes = action.payload;
      })
      .addCase(fetchBookingTypes.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load booking types';
      })

      .addCase(createLifecycleTemplate.fulfilled, (state, action) => {
        const tpl = action.payload;
        const et = tpl.entity_type as EntityType;
        const list = state.templatesByEntity[et] ?? [];
        list.push(tpl);
        state.templatesByEntity[et] = list;
      })
      .addCase(updateLifecycleTemplate.fulfilled, (state, action) => {
        const et = action.payload.entity_type as EntityType;
        const list = state.templatesByEntity[et];
        if (!list) return;
        const idx = list.findIndex((t) => t.id === action.payload.id);
        if (idx !== -1) list[idx] = action.payload;
      })
      .addCase(copyLifecycleTemplate.fulfilled, (state, action) => {
        const et = action.payload.entity_type as EntityType;
        const list = state.templatesByEntity[et] ?? [];
        list.push(action.payload);
        state.templatesByEntity[et] = list;
      })
      .addCase(createBookingType.fulfilled, (state, action) => {
        state.bookingTypes.push(action.payload);
      })
      .addCase(updateBookingType.fulfilled, (state, action) => {
        const idx = state.bookingTypes.findIndex((bt) => bt.id === action.payload.id);
        if (idx !== -1) state.bookingTypes[idx] = action.payload;
      })
      .addCase(deleteLifecycleTemplate.fulfilled, (state, action) => {
        const et = findEntityTypeOf(state.templatesByEntity, action.payload);
        if (et && state.templatesByEntity[et]) {
          state.templatesByEntity[et] = state.templatesByEntity[et]!.filter(
            (t) => t.id !== action.payload
          );
        }
      })
      .addCase(deleteBookingType.fulfilled, (state, action) => {
        state.bookingTypes = state.bookingTypes.filter((bt) => bt.id !== action.payload);
      });
  },
});

/** Selector: booking-only template list (back-compat for code that was
 * reading `state.bookingLifecycle.templates` before the refactor). */
export const selectBookingTemplates = (state: {
  bookingLifecycle: BookingLifecycleState;
}): BookingLifecycleTemplate[] => state.bookingLifecycle.templatesByEntity.booking ?? [];

/** Selector: templates for an arbitrary entity type. */
export const selectTemplatesForEntity = (entityType: EntityType) => (state: {
  bookingLifecycle: BookingLifecycleState;
}): BookingLifecycleTemplate[] => state.bookingLifecycle.templatesByEntity[entityType] ?? [];

export default bookingLifecycleSlice.reducer;
