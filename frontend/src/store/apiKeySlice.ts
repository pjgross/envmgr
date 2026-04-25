// frontend/src/store/apiKeySlice.ts
import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { apiKeyService } from '../services/apiKeyService';
import type { ApiKey, ApiKeyCreatePayload, ApiKeyCreated } from '../types/apiKey';

interface ApiKeyState {
  items: ApiKey[];
  loading: boolean;
  error: string | null;
  justCreated: ApiKeyCreated | null;
}

const initialState: ApiKeyState = {
  items: [],
  loading: false,
  error: null,
  justCreated: null,
};

export const fetchApiKeys = createAsyncThunk('apiKey/fetch', () => apiKeyService.list());
export const createApiKey = createAsyncThunk(
  'apiKey/create',
  (data: ApiKeyCreatePayload) => apiKeyService.create(data),
);
export const revokeApiKey = createAsyncThunk(
  'apiKey/revoke',
  async (id: number) => {
    await apiKeyService.revoke(id);
    return id;
  },
);

const slice = createSlice({
  name: 'apiKey',
  initialState,
  reducers: {
    clearJustCreated(state) {
      state.justCreated = null;
    },
  },
  extraReducers: (b) => {
    b.addCase(fetchApiKeys.pending, (s) => { s.loading = true; s.error = null; });
    b.addCase(fetchApiKeys.fulfilled, (s, a) => { s.loading = false; s.items = a.payload; });
    b.addCase(fetchApiKeys.rejected, (s, a) => {
      s.loading = false;
      s.error = a.error.message ?? 'Failed to load API keys';
    });
    b.addCase(createApiKey.fulfilled, (s, a) => {
      s.justCreated = a.payload;
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      const { raw_key, ...rest } = a.payload;
      s.items = [rest, ...s.items];
    });
    b.addCase(revokeApiKey.fulfilled, (s, a) => {
      s.items = s.items.filter((k) => k.id !== a.payload);
    });
  },
});

export const { clearJustCreated } = slice.actions;
export default slice.reducer;
