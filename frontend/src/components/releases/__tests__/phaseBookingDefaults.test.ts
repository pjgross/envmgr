import { describe, expect, it } from 'vitest';
import { phaseBookingDefaults, toDateInput } from '../phaseBookingDefaults';
import type { TestPhaseResponse } from '../../../types/release';

const phase = (over: Partial<TestPhaseResponse> = {}): TestPhaseResponse => ({
  id: 1,
  tenant_id: 1,
  release_id: 1,
  name: 'SIT',
  order: 0,
  start_date: '2026-08-01',
  end_date: '2026-08-14',
  status: 'planned',
  ...over,
});

describe('toDateInput', () => {
  it('returns "" for null', () => {
    expect(toDateInput(null)).toBe('');
  });
  it('passes through a plain YYYY-MM-DD', () => {
    expect(toDateInput('2026-08-01')).toBe('2026-08-01');
  });
  it('truncates an ISO datetime to the date part', () => {
    expect(toDateInput('2026-08-01T09:30:00Z')).toBe('2026-08-01');
  });
});

describe('phaseBookingDefaults', () => {
  it('builds project name as "<release> - <phase>" and copies phase dates', () => {
    expect(phaseBookingDefaults(phase(), 'Release 2026.08')).toEqual({
      projectName: 'Release 2026.08 - SIT',
      startDate: '2026-08-01',
      endDate: '2026-08-14',
    });
  });

  it('falls back to just the phase name when release name is empty', () => {
    expect(phaseBookingDefaults(phase(), '').projectName).toBe('SIT');
  });

  it('leaves a date blank when the phase has no date', () => {
    const d = phaseBookingDefaults(phase({ start_date: null, end_date: null }), 'R1');
    expect(d.startDate).toBe('');
    expect(d.endDate).toBe('');
  });
});
