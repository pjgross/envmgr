import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { scopeChangeRulesService } from '../services/scopeChangeRulesService';
import type {
  ScopeChangeKindRuleResponse,
  ScopeChangeKindRuleUpsertItem,
} from '../types/scopeChangeRule';

interface ScopeChangeRulesState {
  rules: ScopeChangeKindRuleResponse[];
  kinds: string[];
  kindsLoaded: boolean;
  loading: boolean;
  error: string | null;
}

const initialState: ScopeChangeRulesState = {
  rules: [],
  kinds: [],
  kindsLoaded: false,
  loading: false,
  error: null,
};

export const fetchScopeChangeRules = createAsyncThunk(
  'scopeChangeRules/fetch',
  () => scopeChangeRulesService.list()
);

export const fetchScopeChangeKinds = createAsyncThunk(
  'scopeChangeRules/fetchKinds',
  () => scopeChangeRulesService.listKinds()
);

export const upsertScopeChangeRules = createAsyncThunk(
  'scopeChangeRules/upsert',
  (rules: ScopeChangeKindRuleUpsertItem[]) =>
    scopeChangeRulesService.upsert({ rules })
);

const scopeChangeRulesSlice = createSlice({
  name: 'scopeChangeRules',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(fetchScopeChangeRules.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(fetchScopeChangeRules.fulfilled, (state, action) => {
        state.loading = false;
        state.rules = action.payload;
        state.kinds = action.payload.map((r) => r.change_kind);
        state.kindsLoaded = true;
      })
      .addCase(fetchScopeChangeRules.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load scope change rules';
      })
      .addCase(fetchScopeChangeKinds.fulfilled, (state, action) => {
        state.kinds = action.payload;
        state.kindsLoaded = true;
      })
      .addCase(upsertScopeChangeRules.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(upsertScopeChangeRules.fulfilled, (state, action) => {
        state.loading = false;
        state.rules = action.payload;
        state.kinds = action.payload.map((r) => r.change_kind);
        state.kindsLoaded = true;
      })
      .addCase(upsertScopeChangeRules.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to save scope change rules';
      });
  },
});

export default scopeChangeRulesSlice.reducer;
