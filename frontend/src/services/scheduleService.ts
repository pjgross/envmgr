import api from './api';

export interface ScheduleBooking {
  id: number;
  environment_id: number;
  project_name: string;
  start_date: string;
  end_date: string;
  status: string;
}

export interface ScheduleChangeRequest {
  id: number;
  environment_id: number;
  subsystem_id: number;
  title: string;
  change_type: string;
  status: string;
  scheduled_start: string;
  scheduled_end: string;
  has_outage: boolean;
  outage_start: string | null;
  outage_end: string | null;
}

export interface EnvironmentScheduleResponse {
  environment_id: number;
  start_date: string;
  end_date: string;
  bookings: ScheduleBooking[];
  change_requests: ScheduleChangeRequest[];
  /** Phase 4 will populate; always empty today. */
  deployments: unknown[];
}

export const scheduleService = {
  getEnvironmentSchedule: (
    envId: number,
    startDate: Date,
    endDate: Date
  ): Promise<EnvironmentScheduleResponse> =>
    api
      .get(`/environments/${envId}/schedule`, {
        params: { start_date: startDate.toISOString(), end_date: endDate.toISOString() },
      })
      .then((r) => r.data),
};
