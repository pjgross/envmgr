export type GateCriterionStatus = 'open' | 'done';

export interface GateCriterion {
  id: number;
  gate_id: number;
  title: string;
  notes: string | null;
  due_date: string | null;
  assigned_to_user_id: number | null;
  assigned_to_username: string | null;
  status: GateCriterionStatus;
  completed_at: string | null;
  completed_by_user_id: number | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
}

export interface GateCriterionWithGate extends GateCriterion {
  gate_name: string;
}

export interface GateCriterionCreatePayload {
  title: string;
  notes?: string | null;
  due_date?: string | null;
  assigned_to_user_id?: number | null;
}

export interface GateCriterionUpdatePayload {
  title?: string;
  notes?: string | null;
  due_date?: string | null;
  assigned_to_user_id?: number | null;
}
