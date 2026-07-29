import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EnvironmentOperatingHoursTab from '../EnvironmentOperatingHoursTab';

vi.mock('../../../services/environmentOperatingHoursService', () => ({
  environmentOperatingHoursService: {
    getConfig: vi.fn().mockResolvedValue({
      configured: true,
      timezone: 'Europe/London',
      week: [
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: false, open: '09:00', close: '17:00' },
        { closed: true },
        { closed: true },
      ],
    }),
    putConfig: vi.fn(),
    utilization: vi.fn().mockResolvedValue({
      environment_id: 1, environment_name: 'SIT', configured: true, timezone: 'Europe/London',
      total_operating_seconds: 40 * 3600, booked_operating_seconds: 10 * 3600, utilization_ratio: 0.25,
    }),
    overview: vi.fn(),
  },
}));

describe('EnvironmentOperatingHoursTab', () => {
  it('loads the timezone from the existing config', async () => {
    render(<EnvironmentOperatingHoursTab envId={1} />);
    expect(await screen.findByDisplayValue('Europe/London')).toBeInTheDocument();
  });

  it('shows the utilization card percentage', async () => {
    render(<EnvironmentOperatingHoursTab envId={1} />);
    expect(await screen.findByText('25%')).toBeInTheDocument();
  });
});
