export type PirStatus = 'draft' | 'complete';
export interface PIR {
  id: number; release_id: number; incident_id: number | null;
  summary: string | null; root_cause: string | null;
  what_went_well: string | null; what_went_wrong: string | null; action_plan: string | null;
  status: PirStatus; completed_at: string | null;
}
export interface PIRWrite {
  incident_id?: number | null; summary?: string | null; root_cause?: string | null;
  what_went_well?: string | null; what_went_wrong?: string | null; action_plan?: string | null;
  status?: PirStatus;
}
