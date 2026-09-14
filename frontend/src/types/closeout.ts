export type HypercareState = 'none' | 'planned' | 'active' | 'overdue' | 'stable';

export interface CloseTarget {
  state_key: string;
  label: string;
  requires_pir_complete: boolean;
  requires_handover_confirmed: boolean;
  unmet: string[];
  can_close: boolean;
}

export interface CloseoutRead {
  hypercare: {
    state: HypercareState;
    phase: { id: number; name: string; start_date: string | null; end_date: string | null } | null;
    declared_stable_at: string | null;
    declared_stable_by_username: string | null;
  };
  handover: {
    operations_group_id: number | null;
    operations_group_name: string | null;
    confirmed_at: string | null;
    confirmed_by_username: string | null;
  };
  pir: { exists: boolean; status: string | null; completed_at: string | null };
  incidents: {
    window_start: string | null;
    window_end: string | null;
    by_severity: Record<string, number>;
    total: number;
    items: { id: number; title: string; severity: string; status: string; detected_at: string }[];
  };
  close_targets: CloseTarget[];
}
