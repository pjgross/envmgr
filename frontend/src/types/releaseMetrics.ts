export interface ReleaseMetrics {
  success_rate: number;      // 0..1
  shipped_count: number;
  failed_count: number;
  emergency_pct: number;     // 0..1
  emergency_count: number;
  closed_count: number;
  avg_cycle_time_seconds: number;
  cycle_time_count: number;
}

export interface BookingConflictRow {
  environment_id: number;
  environment_name: string;
  month: string;             // "YYYY-MM"
  conflict_count: number;
}

export interface ReleaseMetricsParams {
  date_from: string;         // "YYYY-MM-DD"
  date_to: string;           // "YYYY-MM-DD"
}
