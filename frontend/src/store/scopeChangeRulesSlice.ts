import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';
import { scopeChangeRulesService } from '../services/scopeChangeRulesService';
import type {
  ScopeChangeKindRuleResponse,
  ScopeChangeKindRuleUpsertItem,
} from '../types/scopeChangeRule';

interface ScopeChangeRulesState {
  rules: ScopeChangeKindRuleResponse[];
  loading: boolean;
  error: string | null;
}

const initialState: ScopeChangeRulesState = {
  rules: [],
  loading: false,
  error: null,
};

export const fetchScopeChangeRules = createAsyncThunk(
  'scopeChangeRules/fetch',
  () => scopeChangeRulesService.list()
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
      })
      .addCase(fetchScopeChangeRules.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to load scope change rules';
      })
      .addCase(upsertScopeChangeRules.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(upsertScopeChangeRules.fulfilled, (state, action) => {
        state.loading = false;
        state.rules = action.payload;
      })
      .addCase(upsertScopeChangeRules.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'Failed to save scope change rules';
      });
  },
});

export default scopeChangeRulesSlice.reducer;
