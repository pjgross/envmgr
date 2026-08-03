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

  it('does not claim a clean bill of health when a detector could not check absence', async () => {
    // Reproduces the reviewer's finding: has_drift is computed only from the
    // categories that WERE computed, so a truncated read with nothing
    // concretely different still yields has_drift=false overall. The
    // unqualified "No drift found" success banner must not appear in that
    // case — it would sit directly above a warning saying the repository
    // could only be read in part, contradicting it. A qualified, non-success
    // message must appear instead.
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        has_drift: false,
        absence_computed: false,
        absence_reason: 'GitHub returned only part of this repository.',
        subsystems: { missing_in_catalogue: [], missing_in_code: null, changed: [] },
        edges: { missing_in_catalogue: [], missing_in_code: null, changed: [] },
      })], { has_drift: false, truncated: true }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    await screen.findByText(/only part of this repository/i);

    expect(
      screen.queryByText(/no drift found.*catalogue matches the code/i),
    ).not.toBeInTheDocument();
    // Something must still tell the user drift wasn't found in what could be
    // read — just not phrased (or coloured) as a clean bill of health.
    expect(
      screen.getByText(/no differences.*parts of the repository that could be read/i),
    ).toBeInTheDocument();
    const alerts = screen.getAllByRole('alert');
    const qualified = alerts.find((a) =>
      /parts of the repository that could be read/i.test(a.textContent ?? ''),
    );
    expect(qualified).toBeTruthy();
    expect(qualified?.className).not.toMatch(/success/i);
  });

  it('omits the edges "no longer in the code" group when its absence was not computed', async () => {
    // Mutation-proven gap: no prior test set edges.missing_in_code to null,
    // so the null-guard on that section (mirroring the subsystem one) could
    // be dropped and every test still passed. A null edges.missing_in_code
    // must not render the "Dependencies in EnvManager, no longer in the
    // code" heading at all — rendering it over an empty list would read as
    // "nothing is missing", the opposite of "we could not check".
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        absence_computed: false,
        absence_reason: 'GitHub returned only part of this repository.',
        edges: {
          missing_in_catalogue: [{
            from_name: 'api', to_name: 'db', port: 5432, source_path: 'docker-compose.yml',
          }],
          missing_in_code: null,
          changed: [],
        },
      })], { truncated: true }) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('api → db')).toBeInTheDocument();
    expect(
      screen.queryByText(/dependencies in envmanager, no longer in the code/i),
    ).not.toBeInTheDocument();
  });

  it('renders non-empty missing_in_code groups by name, with the not-deleted/will-be-removed captions', async () => {
    // The one category this report exists for — reversion drift — had never
    // been rendered non-empty in a test; every prior test exercised
    // missing_in_code as empty or null. Assert both the subsystem and edge
    // groups render their entities BY NAME, and that the two captions keep
    // their (counter-intuitive) meanings: subsystems are never deleted by a
    // scan, dependency edges are deleted and rewritten on every scan.
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        subsystems: {
          missing_in_catalogue: [],
          missing_in_code: ['legacy-worker', 'old-cache'],
          changed: [],
        },
        edges: {
          missing_in_catalogue: [],
          missing_in_code: [
            { from_name: 'api', to_name: 'legacy-worker', port: 6379, source_path: 'docker-compose.yml' },
          ],
          changed: [],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('legacy-worker')).toBeInTheDocument();
    expect(screen.getByText('old-cache')).toBeInTheDocument();
    expect(screen.getByText('api → legacy-worker')).toBeInTheDocument();

    expect(
      screen.getByText(/scanning will not remove these — the scanner never deletes/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/scanning will remove these.*deleted and rewritten/i),
    ).toBeInTheDocument();
  });

  it('shows the edge port and source_path as context, when present', async () => {
    // port is the only comparable edge attribute — the sole thing that can
    // make an edge "changed" — and source_path is the same context the
    // subsystem groups already show. Both were computed and returned by the
    // backend but silently dropped by this component.
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        edges: {
          missing_in_catalogue: [
            { from_name: 'api', to_name: 'redis', port: 6379, source_path: 'docker-compose.yml' },
          ],
          missing_in_code: [],
          changed: [],
        },
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText('api → redis')).toBeInTheDocument();
    expect(screen.getByText('port 6379 · docker-compose.yml')).toBeInTheDocument();
  });

  it('clears the stale report when a re-check fails', async () => {
    // handleCheck used to set `error` without clearing `result`, so a second
    // check that fails renders the red banner above the PREVIOUS report,
    // which a user reads as still-current.
    vi.mocked(githubIntegrationService.drift).mockResolvedValueOnce(
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

    vi.mocked(githubIntegrationService.drift).mockRejectedValueOnce(new Error('upstream 502'));
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(await screen.findByText(/upstream 502/i)).toBeInTheDocument();
    expect(screen.queryByText('payments-api')).not.toBeInTheDocument();
  });

  it('names each detector\'s duplicate warnings without a key collision', async () => {
    // parse_terraform_hcl emits the identical warning string for different
    // files — two occurrences keyed on the message alone collide as React
    // keys. This doesn't assert on React's internals directly, but confirms
    // both instances of the duplicate message actually render.
    vi.mocked(githubIntegrationService.drift).mockResolvedValue(
      result([detector({
        warnings: [
          'skipped a resource block that was not a mapping',
          'skipped a resource block that was not a mapping',
        ],
      })]) as never,
    );

    render(<DriftDialog open systemId={1} onClose={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: /check drift/i }));

    expect(
      await screen.findAllByText('skipped a resource block that was not a mapping'),
    ).toHaveLength(2);
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
