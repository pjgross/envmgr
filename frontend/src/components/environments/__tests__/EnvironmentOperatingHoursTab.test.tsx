import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import EnvironmentOperatingHoursTab from '../EnvironmentOperatingHoursTab';
import { environmentOperatingHoursService } from '../../../services/environmentOperatingHoursService';

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

  it('saves and shows a success snackbar', async () => {
    vi.mocked(environmentOperatingHoursService.putConfig).mockResolvedValueOnce({
      configured: true, timezone: 'UTC', week: [],
    });
    render(<EnvironmentOperatingHoursTab envId={1} />);
    await screen.findByDisplayValue('Europe/London'); // wait for config load
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(await screen.findByText('Operating hours saved')).toBeInTheDocument();
  });

  it('shows an error alert when save fails', async () => {
    vi.mocked(environmentOperatingHoursService.putConfig).mockRejectedValueOnce(new Error('boom'));
    render(<EnvironmentOperatingHoursTab envId={1} />);
    await screen.findByDisplayValue('Europe/London');
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});
