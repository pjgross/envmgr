export interface SeriesPoint { period: string; [metric: string]: number | string; }

export interface DeploymentFrequency { total: number; series: { period: string; count: number }[]; }
export interface LeadTime { median_seconds: number; p90_seconds: number; count: number; series: { period: string; median_seconds: number }[]; }
export interface ChangeFailureRate { rate: number; failed_count: number; shipped_count: number; }
export interface Mttr { mean_seconds: number; median_seconds: number; count: number; series: { period: string; mean_seconds: number }[]; }

export interface DoraSummary {
  deployment_frequency: DeploymentFrequency;
  lead_time: LeadTime;
  change_failure_rate: ChangeFailureRate;
  mttr: Mttr;
}

export interface DoraParams {
  date_from: string;
  date_to: string;
  environment_id?: number;
  release_id?: number;
  granularity?: 'day' | 'week' | 'month';
}
