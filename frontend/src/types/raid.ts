// RAID log (Risks / Assumptions / Issues / Dependencies) types.
// Mirrors backend schemas in app/api/v1/schemas/raid.py.

export type RaidItemType = 'risk' | 'assumption' | 'issue' | 'dependency';

export type RaidRag = 'green' | 'amber' | 'red';

export type RaidRelation = 'relates_to' | 'caused_by' | 'duplicates' | 'blocks';

export interface RaidItemResponse {
  id: number;
  tenant_id: number;
  release_id: number;
  item_type: RaidItemType;
  seq: number;
  ref_code: string;
  title: string;
  description: string | null;
  status: string;
  owner_id: number | null;
  raised_by: number;
  raised_at: string;
  target_date: string | null;
  review_date: string | null;
  closed_at: string | null;
  // scoring (risk / issue)
  probability: number | null;
  impact: number | null;
  severity: number | null;
  rag: RaidRag | null;
  // risk
  response_strategy: string | null;
  mitigation_plan: string | null;
  contingency_plan: string | null;
  // assumption
  validation_status: string | null;
  validated_at: string | null;
  evidence: string | null;
  // issue
  resolution_plan: string | null;
  resolved_at: string | null;
  escalated: boolean;
  // dependency
  direction: string | null;
  counterparty: string | null;
  due_date: string | null;
  at_risk: boolean;
  release_dependency_id: number | null;
  // promotion
  promoted_from_id: number | null;
  custom_fields: Record<string, unknown> | null;
}

export interface RaidItemCreatePayload {
  item_type: RaidItemType;
  title: string;
  description?: string | null;
  owner_id?: number | null;
  target_date?: string | null;
  review_date?: string | null;
  probability?: number | null;
  impact?: number | null;
  response_strategy?: string | null;
  mitigation_plan?: string | null;
  contingency_plan?: string | null;
  evidence?: string | null;
  resolution_plan?: string | null;
  direction?: string | null;
  counterparty?: string | null;
  due_date?: string | null;
  release_dependency_id?: number | null;
  custom_fields?: Record<string, unknown> | null;
}

export interface RaidItemUpdatePayload {
  title?: string;
  description?: string | null;
  status?: string;
  owner_id?: number | null;
  target_date?: string | null;
  review_date?: string | null;
  probability?: number | null;
  impact?: number | null;
  response_strategy?: string | null;
  mitigation_plan?: string | null;
  contingency_plan?: string | null;
  validation_status?: string | null;
  evidence?: string | null;
  resolution_plan?: string | null;
  escalated?: boolean;
  direction?: string | null;
  counterparty?: string | null;
  due_date?: string | null;
  at_risk?: boolean;
  custom_fields?: Record<string, unknown> | null;
}

export interface RaidListFilters {
  item_type?: RaidItemType;
  status?: string;
  owner_id?: number;
  rag?: RaidRag;
  overdue?: boolean;
}

export interface RaidRelationRef {
  to_item_id: number;
  relation: RaidRelation;
}

export interface RaidLinksResponse {
  scope_change_ids: number[];
  relations: RaidRelationRef[];
}

export interface RaidSummaryResponse {
  counts_by_type: Record<string, number>;
  counts_by_rag: Record<string, number>;
  open_issues: number;
  overdue_reviews: number;
  // heatmap[probability-1][impact-1] = [ref_code, ...]
  heatmap: string[][][];
}

export interface RaidRollupTopRisk {
  ref_code: string;
  release_id: number;
  title: string;
  severity: number | null;
  rag: RaidRag | null;
}

export interface RaidRollupResponse {
  counts_by_type: Record<string, number>;
  counts_by_rag: Record<string, number>;
  open_issues: number;
  overdue_reviews: number;
  top_risks: RaidRollupTopRisk[];
}

// --- Config (tenant scoring scales + RAG bands) ---

export interface RaidScaleLevel {
  level: number;
  label: string;
  color: string;
}

export interface RaidBand {
  rag: RaidRag;
  min: number;
  max: number;
  color: string;
}

export interface RaidConfig {
  probability_scale: RaidScaleLevel[];
  impact_scale: RaidScaleLevel[];
  rag_bands: RaidBand[];
}

export interface RaidConfigUpdatePayload {
  probability_scale?: RaidScaleLevel[];
  impact_scale?: RaidScaleLevel[];
  rag_bands?: RaidBand[];
}

export const RAID_TYPE_LABELS: Record<RaidItemType, string> = {
  risk: 'Risks',
  assumption: 'Assumptions',
  issue: 'Issues',
  dependency: 'Dependencies',
};

export const RAID_RELATION_LABELS: Record<RaidRelation, string> = {
  relates_to: 'Relates to',
  caused_by: 'Caused by',
  duplicates: 'Duplicates',
  blocks: 'Blocks',
};
