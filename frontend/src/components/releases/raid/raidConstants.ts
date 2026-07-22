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

/**
 * Readable text colour for a given fill — dark ink on light fills (e.g. amber),
 * white on dark fills. Keeps RAG chips/heat-map cells above WCAG AA.
 */
export function contrastText(hex?: string): string {
  const dark = 'rgba(0, 0, 0, 0.87)';
  if (!hex) return dark;
  const parts = hex.replace('#', '').match(/.{2}/g);
  if (!parts) return dark;
  const [r, g, b] = parts.map((h) => {
    const v = parseInt(h, 16) / 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  });
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance > 0.45 ? dark : '#fff';
}

/** `sx` for a RAG-coloured chip with an accessible foreground. */
export function ragChipSx(rag: RaidRag | null | undefined, config: RaidConfig | null) {
  const bg = ragColor(rag, config);
  return { bgcolor: bg, color: contrastText(bg) };
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
