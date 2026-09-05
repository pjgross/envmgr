// GET /me/work — Phase "IA" Task 4/5: the five "waiting on me" queues a
// personal inbox composes under one clock. Mirrors
// backend/app/api/v1/schemas/my_work.py exactly.
//
// `title` is ALWAYS a name, never a bare id — the backend never sends a
// `#42` fallback (see CLAUDE.md's display-names rule), so nothing here needs
// to resolve `id` against anything else to render a row.
export interface WorkItem {
  id: number;
  title: string;
  subtitle?: string | null;
  /** The detail route this row opens. */
  url: string;
  /** ISO datetime, or absent when the item carries no deadline. */
  due?: string | null;
}

/**
 * `failed` is NOT the same value as an empty queue (§5). A queue whose
 * underlying worklist query blew up comes back as `{ count: 0, items: [],
 * failed: true }` — indistinguishable from an empty one by `count`/`items`
 * alone, which is exactly why every consumer must branch on `failed` FIRST.
 */
export interface QueueResult {
  count: number;
  items: WorkItem[];
  /** `pir_actions` only. */
  overdue?: number;
  failed: boolean;
}

export type MyWorkQueueKey =
  | 'environment_requests'
  | 'contentions'
  | 'decommissions'
  | 'pir_actions'
  | 'incidents';

export interface MyWorkResponse {
  as_of: string;
  queues: Record<MyWorkQueueKey, QueueResult>;
}
