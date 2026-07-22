// Shared RAID presentation helpers.
import type { RaidItemType, RaidRag, RaidConfig } from '../../../types/raid';

export const RAID_TYPES: RaidItemType[] = ['risk', 'assumption', 'issue', 'dependency'];

// Fixed status lifecycles (match backend raid_service).
export const RAID_STATUSES: Record<RaidItemType, string[]> = {
  risk: ['open', 'mitigating', 'closed', 'promoted'],
  assumption: ['open', 'closed'],
  issue: ['open', 'in_progress', 'resolved', 'closed'],
  dependency: ['identified', 'in_progress', 'met', 'closed'],
};

export const VALIDATION_STATUSES = ['unvalidated', 'validated', 'invalidated'];
export const RESPONSE_STRATEGIES = ['avoid', 'reduce', 'transfer', 'accept'];
export const DEPENDENCY_DIRECTIONS = ['inbound', 'outbound'];

const RAG_FALLBACK: Record<RaidRag, string> = {
  green: '#4caf50',
  amber: '#ff9800',
  red: '#f44336',
};

/** Colour for a RAG value, preferring the tenant's configured band colour. */
export function ragColor(rag: RaidRag | null | undefined, config: RaidConfig | null): string | undefined {
  if (!rag) return undefined;
  const band = config?.rag_bands.find((b) => b.rag === rag);
  return band?.color ?? RAG_FALLBACK[rag];
}

/** Colour for a raw severity score, using the tenant's configured bands. */
export function severityColor(severity: number, config: RaidConfig | null): string | undefined {
  const band = config?.rag_bands.find((b) => severity >= b.min && severity <= b.max);
  if (band) return band.color;
  if (severity <= 5) return RAG_FALLBACK.green;
  if (severity <= 14) return RAG_FALLBACK.amber;
  return RAG_FALLBACK.red;
}

/** Is this item an overdue review? (review_date in the past and not yet closed) */
export function isOverdueReview(reviewDate: string | null, status: string): boolean {
  if (!reviewDate) return false;
  if (status === 'closed' || status === 'met' || status === 'promoted') return false;
  return new Date(reviewDate).getTime() < Date.now();
}

export function titleCase(s: string): string {
  return s
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}
