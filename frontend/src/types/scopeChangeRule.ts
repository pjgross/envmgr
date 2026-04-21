export interface ScopeChangeKindRuleResponse {
  id: number;
  change_kind: string;
  counts_as_scope_change: boolean;
}

export interface ScopeChangeKindRuleUpsertItem {
  change_kind: string;
  counts_as_scope_change: boolean;
}

export interface ScopeChangeKindRulesUpsertPayload {
  rules: ScopeChangeKindRuleUpsertItem[];
}
