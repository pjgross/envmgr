export type GateCriterionStatus = 'open' | 'done';

export interface GateCriterion {
  id: number;
  gate_id: number;
  title: string;
  notes: string | null;
  assigned_to_user_id: number | null;
  assigned_to_username: string | null;
  assigned_role: string | null;
  status: GateCriterionStatus;
  completed_at: string | null;
  completed_by_user_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface GateCriterionWithGate extends GateCriterion {
  gate_name: string;
  gate_due_date: string;
}

export interface GateCriterionCreatePayload {
  title: string;
  notes?: string | null;
  assigned_to_user_id?: number | null;
  assigned_role?: string | null;
}

export interface GateCriterionUpdatePayload {
  title?: string;
  notes?: string | null;
  assigned_to_user_id?: number | null;
  assigned_role?: string | null;
}
