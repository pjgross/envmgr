import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import DriftDialog from '../DriftDialog';
import { githubIntegrationService } from '../../../services/githubIntegrationService';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: { drift: vi.fn() },
}));

const detector = (overrides = {}) => ({
  detector: 'docker_compose',
  paths: ['docker-compose.yml'],
  paths_unread: 0,
  errors: [],
  warnings: [],
  absence_computed: true,
  absence_reason: null,
  has_drift: true,
  subsystems: { missing_in_catalogue: [], missing_in_code: [], changed: [] },
  edges: { missing_in_catalogue: [], missing_in_code: [], changed: [] },
  ...overrides,
});

const result = (detectors: unknown[], overrides = {}) => ({
  ref: 'main',
  files_scanned: 1,
  truncated: false,
  stopped_early: false,
  has_drift: true,
  detectors,
  ...overrides,
});

describe('DriftDialog', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('names each drifted subsystem rather than counting them', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [{
            name: 'payments-api', component_type: 'web_service',
            technology: 'nginx', source_path: 'docker-compose.yml',
          }],
          missing_in_code: [],
          changed: [],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('payments-api')).toBeInTheDocument();
  });

  it('states the positive when nothing has drifted', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({ has_drift: false })], { has_drift: false }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(
      await screen.findByText(/catalogue matches the code/i),
    ).toBeInTheDocument();
  });

  it('explains why absence was not checked and omits the group entirely', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        absence_computed: false,
        absence_reason: 'GitHub returned only part of this repository.',
        subsystems: {
          missing_in_catalogue: [{
            name: 'api', component_type: 'web_service',
            technology: null, source_path: 'docker-compose.yml',
          }],
          missing_in_code: null,
          changed: [],
        },
      })], { truncated: true }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText(/only part of this repository/i)).toBeInTheDocument();
    // The heading must be absent, not present over an empty list: rendering it
    // empty would read as "nothing is missing", the opposite conclusion.
    expect(screen.queryByText(/no longer in the code/i)).not.toBeInTheDocument();
  });

  it('does not announce success while drift is listed', async () => {
    // Mutation-proven gap: the dialog-level success alert ("No drift found —
    // the catalogue matches the code.") must only render when has_drift is
    // false. Nothing previously asserted its ABSENCE, so a dialog that both
    // lists a missing subsystem and announces success would pass every
    // existing test — a page contradicting itself is worse than one that
    // reports nothing. Assert against the dialog-level alert text only; the
    // per-detector "No drift detected by this detector." text is a distinct
    // string and must not be confused with it.
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [{
            name: 'payments-api', component_type: 'web_service',
            technology: 'nginx', source_path: 'docker-compose.yml',
          }],
          missing_in_code: [],
          changed: [],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('payments-api')).toBeInTheDocument();
    expect(
      screen.queryByText(/no drift found.*catalogue matches the code/i),
    ).not.toBeInTheDocument();
  });

  it('shows both values for a changed field', async () => {
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [],
          missing_in_code: [],
          changed: [{
            name: 'api', field: 'component_type', catalogue: 'other',
            declared: 'web_service', source_path: 'docker-compose.yml',
          }],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText(/other/)).toBeInTheDocument();
    expect(screen.getByText(/web_service/)).toBeInTheDocument();
  });
});
