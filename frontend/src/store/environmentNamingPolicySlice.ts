import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';

import {
  environmentNamingPolicyService,
  type NamingPolicyPreviewRequest,
} from '../services/environmentNamingPolicyService';
import { formatApiError } from '../services/apiError';
import type {
  EnvironmentNamingPolicy,
  EnvironmentNamingPolicyPreview,
  EnvironmentNamingPolicyUpdate,
} from '../types/environment';

interface State {
  policy: EnvironmentNamingPolicy | null;
  preview: EnvironmentNamingPolicyPreview | null;
  loading: boolean;
  error: string | null;
}

const initialState: State = { policy: null, preview: null, loading: false, error: null };

export const fetchNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/fetch',
  async (_, { rejectWithValue }) => {
    try {
      return await environmentNamingPolicyService.get();
    } catch (err) {
      return rejectWithValue(formatApiError(err));
    }
  }
);

export const saveNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/save',
  async (data: EnvironmentNamingPolicyUpdate, { rejectWithValue }) => {
    try {
      return await environmentNamingPolicyService.save(data);
    } catch (err) {
      // rejectWithValue(formatApiError(err)) and NOT the default serializer:
      // miniSerializeError copies only name/message/stack/code, so the
      // server's response.data.detail — the actual reason, and here the
      // worked example a valid name must look like — is dropped.
      return rejectWithValue(formatApiError(err));
    }
  }
);

export const previewNamingPolicy = createAsyncThunk(
  'environmentNamingPolicy/preview',
  async (data: NamingPolicyPreviewRequest, { rejectWithValue }) => {
    try {
      return await environmentNamingPolicyService.preview(data);
    } catch (err) {
      return rejectWithValue(formatApiError(err));
    }
  }
);

const slice = createSlice({
  name: 'environmentNamingPolicy',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchNamingPolicy.pending, (s) => {
        s.loading = true;
        s.error = null;
        // Cleared on pending, not only on fulfilled: a panel that outlives an
        // unmount would otherwise render the previous tenant's policy under
        // the new one's heading.
        s.policy = null;
        s.preview = null;
      })
      .addCase(fetchNamingPolicy.fulfilled, (s, a) => {
        s.loading = false;
        s.policy = a.payload;
      })
      .addCase(fetchNamingPolicy.rejected, (s, a) => {
        s.loading = false;
        s.error = a.payload as string;
      })
      .addCase(saveNamingPolicy.fulfilled, (s, a) => {
        s.policy = a.payload;
        s.error = null;
        // The saved rule may differ from the one previewed, so the old counts
        // no longer describe anything the admin can act on.
        s.preview = null;
      })
      .addCase(saveNamingPolicy.rejected, (s, a) => {
        s.error = a.payload as string;
      })
      .addCase(previewNamingPolicy.pending, (s) => {
        s.preview = null;
        s.error = null;
      })
      .addCase(previewNamingPolicy.fulfilled, (s, a) => {
        s.preview = a.payload;
      })
      .addCase(previewNamingPolicy.rejected, (s, a) => {
        s.error = a.payload as string;
      });
  },
});

export default slice.reducer;
