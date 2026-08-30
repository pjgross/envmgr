import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ReleasePirTab from '../ReleasePirTab';
import { pirService } from '../../../../services/pirService';
import type { PIR } from '../../../../types/pir';

vi.mock('../../../../services/pirService', () => ({
  pirService: {
    getForRelease: vi.fn(), create: vi.fn(), update: vi.fn(),
    createFinding: vi.fn(), updateFinding: vi.fn(), deleteFinding: vi.fn(),
    createAction: vi.fn(), updateAction: vi.fn(), deleteAction: vi.fn(),
    citeIncident: vi.fn(), unciteIncident: vi.fn(),
  },
}));

// The owner picker reads GET /tenant/users/lite straight through `api`, the
// same way GatesTable and ContentionVerdict do.
vi.mock('../../../../services/api', () => ({
  default: { get: vi.fn().mockResolvedValue({ data: [{ id: 5, username: 'alice' }] }) },
}));

const mocked = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;

const pir = (overrides: Partial<PIR> = {}): PIR => ({
  id: 1, release_id: 3, summary: 'Went out late', status: 'draft', completed_at: null,
  findings: [
    {
      id: 10, kind: 'went_well', seq: 1, title: 'Canary caught it', detail: null,
      root_cause: null, created_at: '2026-08-01T00:00:00Z', actions: [], incidents: [],
    },
    {
      id: 11, kind: 'went_wrong', seq: 1, title: 'No load test before go-live',
      detail: 'Perf suite is opt-in', root_cause: 'The perf gate is optional',
      created_at: '2026-08-01T00:00:00Z',
      actions: [{
        id: 20, finding_id: 11, seq: 1, title: 'Make the perf gate mandatory', detail: null,
        owner_id: 5, owner_username: 'alice', due_date: '2026-09-30T00:00:00Z', status: 'open',
        closed_at: null, closure_note: null, is_overdue: true,
      }],
      incidents: [{
        incident_id: 41, incident_title: 'Checkout 500s', severity: 'P1', status: 'open',
        note: null,
      }],
    },
  ],
  ...overrides,
});

const renderTab = () =>
  render(<MemoryRouter><ReleasePirTab releaseId={3} /></MemoryRouter>);

beforeEach(() => vi.resetAllMocks());

describe('ReleasePirTab', () => {
  it('renders went-well findings before went-wrong ones', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    await screen.findByText('Canary caught it');
    const text = screen.getAllByRole('heading').map((h) => h.textContent).join('|');
    expect(text.indexOf('What went well')).toBeLessThan(text.indexOf('What went wrong'));
  });

  it('shows a went-wrong finding with its root cause', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    expect(await screen.findByText('The perf gate is optional')).toBeInTheDocument();
  });

  it("names an action's owner rather than its id", async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    expect(await screen.findByText('alice')).toBeInTheDocument();
    expect(screen.queryByText(/#5|user 5/i)).not.toBeInTheDocument();
  });

  it("takes the server's overdue verdict rather than comparing dates itself", async () => {
    // due_date is far in the future, but the server said overdue. The page must
    // agree with the server, not with the browser's clock.
    const body = pir();
    body.findings[1].actions[0].due_date = '2099-01-01T00:00:00Z';
    mocked.getForRelease.mockResolvedValue(body);
    renderTab();
    expect(await screen.findByText(/overdue/i)).toBeInTheDocument();
  });

  it('does not call an action overdue when the server did not', async () => {
    // The complement, and the one that catches a chip hardcoded on. A due date
    // long past, with is_overdue false — a closed action, say — stays quiet.
    const body = pir();
    body.findings[1].actions[0].due_date = '2020-01-01T00:00:00Z';
    body.findings[1].actions[0].is_overdue = false;
    mocked.getForRelease.mockResolvedValue(body);
    renderTab();
    await screen.findByText('Make the perf gate mandatory');
    expect(screen.queryByText(/overdue/i)).not.toBeInTheDocument();
  });

  it('shows a cited incident by name, linking to it', async () => {
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    const link = await screen.findByRole('link', { name: /Checkout 500s/ });
    expect(link).toHaveAttribute('href', '/incidents/41');
  });

  it('offers to create a PIR when the release has none, and creates it', async () => {
    mocked.getForRelease.mockResolvedValue(null);
    mocked.create.mockResolvedValue(pir({ findings: [] }));
    renderTab();
    await userEvent.click(await screen.findByRole('button', { name: /create pir/i }));
    await waitFor(() => expect(mocked.create).toHaveBeenCalledWith(3, {}));
  });

  it('re-reads the PIR after a finding is added, rather than patching local state', async () => {
    // Re-render, do not just mount: three bugs on this codebase survived
    // mount-only tests because the second read never happened.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.createFinding.mockResolvedValue({});
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getByRole('button', { name: /add what went wrong/i }));
    await userEvent.type(await screen.findByLabelText(/title/i), 'Rollback took 40 minutes');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(mocked.getForRelease).toHaveBeenCalledTimes(2));
  });

  it('creates a went-wrong finding with the kind fixed by the section it was added from',
    async () => {
      // `kind` is which LIST the finding is in, not a form field. Offering it
      // would let someone file a production failure under "keep doing this".
      mocked.getForRelease.mockResolvedValue(pir());
      mocked.createFinding.mockResolvedValue({});
      renderTab();
      await screen.findByText('Canary caught it');
      await userEvent.click(screen.getByRole('button', { name: /add what went well/i }));
      await userEvent.type(await screen.findByLabelText(/title/i), 'Canary held');
      await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
      await waitFor(() => expect(mocked.createFinding).toHaveBeenCalledWith(
        3, expect.objectContaining({ kind: 'went_well', title: 'Canary held' })));
    });

  it('never sends kind when editing an existing finding', async () => {
    // The backend 422s on a kind CHANGE, and sending the unchanged value makes
    // it a change the moment the dialog is reused for the other kind.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.updateFinding.mockResolvedValue({});
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getAllByRole('button', { name: /edit finding/i })[0]);
    await userEvent.click(await screen.findByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(mocked.updateFinding).toHaveBeenCalled());
    expect(mocked.updateFinding.mock.calls[0][2]).not.toHaveProperty('kind');
  });

  it('shows the server error text, not an HTTP status', async () => {
    // Rejects with an AXIOS ERROR SHAPE, never a plain Error carrying the final
    // text: a plain-Error test passes while the app shows the bare status.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.deleteFinding.mockRejectedValue({
      isAxiosError: true,
      response: { status: 422, data: { detail: 'kind cannot be changed' } },
      message: 'Request failed with status code 422',
    });
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getAllByRole('button', { name: /delete finding/i })[0]);
    await userEvent.click(await screen.findByRole('button', { name: /^delete$/i }));
    expect(await screen.findByText(/kind cannot be changed/i)).toBeInTheDocument();
  });
});
