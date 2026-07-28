import type { TestPhaseResponse } from '../../types/release';

/** Convert an ISO date/datetime string to a `YYYY-MM-DD` value for a date input (or '' if null). */
export function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

export interface PhaseBookingDefaults {
  projectName: string;
  startDate: string;
  endDate: string;
}

/**
 * Booking-form defaults derived from a chosen release phase:
 * - project name `<release name> - <phase name>` (falls back to just the phase name
 *   when the release name is unknown)
 * - start/end dates taken from the phase (blank when the phase has no date set)
 */
export function phaseBookingDefaults(
  phase: TestPhaseResponse,
  releaseName: string,
): PhaseBookingDefaults {
  return {
    projectName: releaseName ? `${releaseName} - ${phase.name}` : phase.name,
    startDate: toDateInput(phase.start_date),
    endDate: toDateInput(phase.end_date),
  };
}
