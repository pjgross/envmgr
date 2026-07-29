export interface OperatingHoursDay {
  closed: boolean;
  open?: string | null;   // "HH:MM"
  close?: string | null;  // "HH:MM"
}

export interface OperatingHoursConfig {
  configured: boolean;
  timezone?: string | null;
  week?: OperatingHoursDay[] | null;
}

export interface OperatingHoursConfigInput {
  timezone: string;
  week: OperatingHoursDay[];
}

export interface EnvironmentUtilization {
  environment_id: number;
  environment_name: string;
  configured: boolean;
  timezone?: string | null;
  total_operating_seconds: number;
  booked_operating_seconds: number;
  utilization_ratio: number; // 0..1
}

export interface UtilizationOverview {
  rows: EnvironmentUtilization[];
  unconfigured_count: number;
}

export interface UtilizationParams {
  date_from: string; // "YYYY-MM-DD"
  date_to: string;   // "YYYY-MM-DD"
}
