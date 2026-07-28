export type HealthStatus = 'up' | 'down' | 'issue' | 'unknown';

export interface HealthSample {
  id: number; environment_id: number; status: 'up' | 'down' | 'issue';
  recorded_at: string; source: string; detail: string | null;
}
export interface ActiveBookingSummary { project_name: string; start_date: string; end_date: string; }
export interface EnvironmentHealthOverviewRow {
  environment_id: number; environment_name: string;
  current_status: HealthStatus; last_recorded_at: string | null;
  active_booking: boolean; active_booking_summary: ActiveBookingSummary | null;
  planned_outage: boolean; alert: boolean;
}
