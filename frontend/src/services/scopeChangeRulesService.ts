import api from './api';
import type {
  ScopeChangeKindRuleResponse,
  ScopeChangeKindRulesUpsertPayload,
} from '../types/scopeChangeRule';

export const scopeChangeRulesService = {
  list: () =>
    api.get<ScopeChangeKindRuleResponse[]>('/tenant/scope-change-rules').then((r) => r.data),
  listKinds: () =>
    api.get<string[]>('/tenant/scope-change-rules/kinds').then((r) => r.data),
  upsert: (payload: ScopeChangeKindRulesUpsertPayload) =>
    api.put<ScopeChangeKindRuleResponse[]>('/tenant/scope-change-rules', payload).then((r) => r.data),
};
