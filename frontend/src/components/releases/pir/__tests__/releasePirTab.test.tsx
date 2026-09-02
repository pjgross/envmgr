import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ReleasePirTab from '../ReleasePirTab';
import api from '../../../../services/api';
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
vi.mock('../../../../services/api', () => ({ default: { get: vi.fn() } }));

const mocked = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mockedApi = api as unknown as { get: ReturnType<typeof vi.fn> };

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

beforeEach(() => {
  vi.resetAllMocks();
  // Re-armed AFTER the reset: `vi.resetAllMocks()` clears implementations, and
  // the owner picker's `api.get(...).then(...)` throws on an unarmed mock — a
  // trap only the tests that open the action dialog ever reach.
  (mockedApi.get as ReturnType<typeof vi.fn>)
    .mockResolvedValue({ data: [{ id: 5, username: 'alice' }] });
});

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

  it('offers a real, named button to remove a citation', async () => {
    // Was a `<Chip onDelete>`, whose delete affordance MUI renders as a bare
    // <svg> with no role, no tabindex and no accessible name — unreachable by
    // keyboard, unannounced by a screen reader, and invisible to this query.
    // Found in the browser pass, not by any test.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.unciteIncident.mockResolvedValue({});
    renderTab();
    await userEvent.click(
      await screen.findByRole('button', { name: /remove evidence checkout 500s/i }));
    await waitFor(() => expect(mocked.unciteIncident).toHaveBeenCalledWith(3, 11, 41));
  });

  it('names the citation link after the incident, not after the note', async () => {
    // The chip's `title` landed on the root element, so the link's accessible
    // name became the note — and varied depending on whether anyone typed one.
    const body = pir();
    body.findings[1].incidents[0].note = 'root incident';
    mocked.getForRelease.mockResolvedValue(body);
    renderTab();
    expect(await screen.findByRole('link', { name: /Checkout 500s/ })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'root incident' })).not.toBeInTheDocument();
    // The note is still shown — as text, not as a tooltip no touch or keyboard
    // user can reach.
    expect(screen.getByText(/root incident/)).toBeInTheDocument();
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

  it('sends a create payload the create endpoint actually accepts', async () => {
    // The component tests mock the service, so a payload the API refuses looks
    // identical to one it accepts. This pins the KEY SET instead: `PirActionCreate`
    // declares extra="forbid", and an unexpected key is a 422 on every save — which
    // is exactly what shipped, and was found only by opening the page.
    mocked.getForRelease.mockResolvedValue(pir());
    mocked.createAction.mockResolvedValue({});
    renderTab();
    await screen.findByText('Canary caught it');
    await userEvent.click(screen.getAllByRole('button', { name: /add action/i })[0]);
    await userEvent.type(await screen.findByLabelText(/title/i), 'A new action');
    await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() => expect(mocked.createAction).toHaveBeenCalled());
    // createAction(releaseId, findingId, data) — the payload is the third arg.
    const payload = mocked.createAction.mock.calls[0][2];
    expect(Object.keys(payload).sort()).toEqual(
      ['closure_note', 'detail', 'due_date', 'owner_id', 'status', 'title']);
  });

  it.each([
    ['editing a finding', async () => {
      mocked.updateFinding.mockResolvedValue({});
      await userEvent.click(screen.getAllByRole('button', { name: /edit finding/i })[0]);
      await userEvent.click(await screen.findByRole('button', { name: /^save$/i }));
    }],
    ['adding an action', async () => {
      mocked.createAction.mockResolvedValue({});
      await userEvent.click(screen.getAllByRole('button', { name: /add action/i })[0]);
      await userEvent.type(await screen.findByLabelText(/title/i), 'A');
      await userEvent.click(screen.getByRole('button', { name: /^save$/i }));
    }],
    ['editing an action', async () => {
      mocked.updateAction.mockResolvedValue({});
      await userEvent.click(screen.getAllByRole('button', { name: /edit action/i })[0]);
      await userEvent.click(await screen.findByRole('button', { name: /^save$/i }));
    }],
    ['removing a citation', async () => {
      mocked.unciteIncident.mockResolvedValue({});
      await userEvent.click(
        screen.getByRole('button', { name: /remove evidence checkout 500s/i }));
    }],
  ])('re-reads the PIR after %s', async (_label, act) => {
    // "Every mutation re-reads the whole PIR rather than patching local state"
    // is the rule that stops a locally-patched row disagreeing with the
    // server's seq numbers, overdue verdicts and action counts — and it was
    // pinned on the create-a-finding path only. A patch-in-place on any of
    // these four would wipe that finding's actions and evidence with the suite
    // green.
    mocked.getForRelease.mockResolvedValue(pir());
    renderTab();
    await screen.findByText('Canary caught it');
    await act();
    await waitFor(() => expect(mocked.getForRelease).toHaveBeenCalledTimes(2));
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
