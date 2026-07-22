import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import type {
  RaidItemResponse,
  RaidItemCreatePayload,
  RaidItemUpdatePayload,
  RaidListFilters,
  RaidSummaryResponse,
  RaidItemType,
  RaidConfig,
  RaidConfigUpdatePayload,
} from '../types/raid';
import { raidService } from '../services/raidService';

interface RaidState {
  items: RaidItemResponse[];
  summary: RaidSummaryResponse | null;
  config: RaidConfig | null;
  loading: boolean;
  error: string | null;
}

const initialState: RaidState = {
  items: [],
  summary: null,
  config: null,
  loading: false,
  error: null,
};

export const fetchRaidItems = createAsyncThunk(
  'raid/list',
  ({ releaseId, filters }: { releaseId: number; filters?: RaidListFilters }) =>
    raidService.list(releaseId, filters),
);

export const createRaidItem = createAsyncThunk(
  'raid/create',
  ({ releaseId, data }: { releaseId: number; data: RaidItemCreatePayload }) =>
    raidService.create(releaseId, data),
);

export const updateRaidItem = createAsyncThunk(
  'raid/update',
  ({ releaseId, itemId, data }: { releaseId: number; itemId: number; data: RaidItemUpdatePayload }) =>
    raidService.update(releaseId, itemId, data),
);

export const deleteRaidItem = createAsyncThunk(
  'raid/delete',
  async ({ releaseId, itemId }: { releaseId: number; itemId: number }) => {
    await raidService.remove(releaseId, itemId);
    return itemId;
  },
);

export const promoteRaidItem = createAsyncThunk(
  'raid/promote',
  ({ releaseId, itemId, targetType }: { releaseId: number; itemId: number; targetType: RaidItemType }) =>
    raidService.promote(releaseId, itemId, targetType),
);

export const fetchRaidSummary = createAsyncThunk('raid/summary', (releaseId: number) =>
  raidService.summary(releaseId),
);

export const fetchRaidConfig = createAsyncThunk('raid/config/get', () => raidService.getConfig());

export const updateRaidConfig = createAsyncThunk(
  'raid/config/update',
  (data: RaidConfigUpdatePayload) => raidService.updateConfig(data),
);

const raidSlice = createSlice({
  name: 'raid',
  initialState,
  reducers: {
    clearRaid(state) {
      state.items = [];
      state.summary = null;
      state.error = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchRaidItems.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchRaidItems.fulfilled, (state, action) => {
        state.loading = false;
        state.items = action.payload;
      })
      .addCase(fetchRaidItems.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load RAID items';
      })

      .addCase(createRaidItem.fulfilled, (state, action) => {
        state.items.push(action.payload);
      })

      .addCase(updateRaidItem.fulfilled, (state, action) => {
        const idx = state.items.findIndex((i) => i.id === action.payload.id);
        if (idx !== -1) state.items[idx] = action.payload;
      })

      .addCase(deleteRaidItem.fulfilled, (state, action) => {
        state.items = state.items.filter((i) => i.id !== action.payload);
      })

      // Promotion creates a new item; the source's status change is reflected
      // on the next fetchRaidItems the caller dispatches.
      .addCase(promoteRaidItem.fulfilled, (state, action) => {
        state.items.push(action.payload);
      })

      .addCase(fetchRaidSummary.fulfilled, (state, action) => {
        state.summary = action.payload;
      })

      .addCase(fetchRaidConfig.fulfilled, (state, action) => {
        state.config = action.payload;
      })
      .addCase(updateRaidConfig.fulfilled, (state, action) => {
        state.config = action.payload;
      });
  },
});

export const { clearRaid } = raidSlice.actions;
export default raidSlice.reducer;
