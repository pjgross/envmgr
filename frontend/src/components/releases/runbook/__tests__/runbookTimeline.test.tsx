import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { RunbookRead } from '../../../../types/runbook';
import RunbookTimeline from '../RunbookTimeline';

const base = {
  description: null, kind: 'task' as const, team_group_id: null, team_name: null, system_id: null, system_name: null,
  system_on_release: true, fixed_start_at: null, actual_started_at: null, actual_finished_at: null, sort_order: 0,
  predecessor_ids: [], late_start: false, overrunning: false, slipped_past_fixed_start: false, blocked: false,
  allowed_transitions: [], status: 'not_started' as const,
};
const read: RunbookRead = {
  plan: { id: 5, release_id: 7, environment_id: 2, environment_name: 'prod', name: 'Cutover',
          anchor_start_at: '2026-10-01T18:00:00Z', deploy_pattern: null, notes: null, state: 'in_progress' },
  planned_end: '2026-10-02T19:00:00Z', forecast_end: '2026-10-02T20:00:00Z', slip_minutes: 60,
  tasks: [
    { ...base, id: 1, name: 'Pre-task', duration_minutes: 60, critical: true,
      planned_start: '2026-10-01T18:00:00Z', planned_finish: '2026-10-01T19:00:00Z',
      forecast_start: '2026-10-01T18:00:00Z', forecast_finish: '2026-10-01T20:00:00Z' },
    { ...base, id: 2, name: 'Evening two check', duration_minutes: 60, critical: false, predecessor_ids: [1],
      planned_start: '2026-10-02T18:00:00Z', planned_finish: '2026-10-02T19:00:00Z',
      forecast_start: '2026-10-02T19:00:00Z', forecast_finish: '2026-10-02T20:00:00Z' },
  ],
};

describe('RunbookTimeline', () => {
  it('draws a planned and a forecast bar per task, with readable labels', () => {
    render(<RunbookTimeline read={read} />);
    expect(screen.getByLabelText(/Pre-task: planned/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Pre-task: forecast .* critical/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Evening two check: forecast/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Evening two check: forecast .* critical/)).not.toBeInTheDocument();
  });

  it('scrolls inside itself rather than widening the page', () => {
    const { container } = render(<RunbookTimeline read={read} />);
    const scroller = container.querySelector('[data-testid="runbook-timeline-scroll"]') as HTMLElement;
    expect(scroller).not.toBeNull();
    expect(scroller.style.overflowX || getComputedStyle(scroller).overflowX).toBe('auto');
  });
});
