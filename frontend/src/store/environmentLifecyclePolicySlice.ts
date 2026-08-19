import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';

import { environmentLifecyclePolicyService } from '../services/environmentLifecyclePolicyService';
import { formatApiError } from '../services/apiError';
import type {
  EnvironmentLifecyclePolicy,
  EnvironmentLifecyclePolicyUpdate,
} from '../types/decommission';

interface State {
  policy: EnvironmentLifecyclePolicy | null;
  loading: boolean;
  error: string | null;
}

const initialState: State = { policy: null, loading: false, error: null };

export const fetchLifecyclePolicy = createAsyncThunk<
  EnvironmentLifecyclePolicy,
  void,
  { rejectValue: string }
>('environmentLifecyclePolicy/fetch', async (_, { rejectWithValue }) => {
  try {
    return await environmentLifecyclePolicyService.get();
  } catch (err) {
    return rejectWithValue(formatApiError(err, 'Failed to load the lifecycle policy'));
  }
});

export const saveLifecyclePolicy = createAsyncThunk<
  EnvironmentLifecyclePolicy,
  EnvironmentLifecyclePolicyUpdate,
  { rejectValue: string }
>('environmentLifecyclePolicy/save', async (data, { rejectWithValue }) => {
  try {
    return await environmentLifecyclePolicyService.save(data);
  } catch (err) {
    // rejectWithValue(formatApiError(err)), never letting the AxiosError
    // escape to RTK's default miniSerializeError — that copies only
    // name/message/stack/code, so a real 422's `response.data.detail` (the
    // actual constraint that was violated) would be dropped in favour of
    // "Request failed with status code 422".
    return rejectWithValue(formatApiError(err, 'Failed to save the lifecycle policy'));
  }
});

const slice = createSlice({
  name: 'environmentLifecyclePolicy',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchLifecyclePolicy.pending, (s) => {
        s.loading = true;
        s.error = null;
        // Cleared on pending, not only on fulfilled — a panel that outlives
        // an unmount must not go on rendering the previous tenant's policy
        // under a new heading (same rule fetchNamingPolicy follows).
        s.policy = null;
      })
      .addCase(fetchLifecyclePolicy.fulfilled, (s, a) => {
        s.loading = false;
        s.policy = a.payload;
      })
      .addCase(fetchLifecyclePolicy.rejected, (s, a) => {
        s.loading = false;
        s.error = a.payload ?? 'Failed to load the lifecycle policy';
      })
      .addCase(saveLifecyclePolicy.fulfilled, (s, a) => {
        s.policy = a.payload;
        s.error = null;
      })
      .addCase(saveLifecyclePolicy.rejected, (s, a) => {
        s.error = a.payload ?? 'Failed to save the lifecycle policy';
      });
  },
});

export default slice.reducer;
