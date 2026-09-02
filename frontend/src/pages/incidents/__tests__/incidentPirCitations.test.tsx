import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LinkIncidentToPirDialog from '../../../components/incidents/LinkIncidentToPirDialog';
import { incidentService } from '../../../services/incidentService';
import { pirService } from '../../../services/pirService';
import { releaseService } from '../../../services/releaseService';

vi.mock('../../../services/incidentService', () => ({
  incidentService: { citeOnPir: vi.fn() },
}));
vi.mock('../../../services/pirService', () => ({
  pirService: { getForRelease: vi.fn() },
}));
vi.mock('../../../services/releaseService', () => ({
  releaseService: { list: vi.fn() },
}));

const releases = releaseService as unknown as Record<string, ReturnType<typeof vi.fn>>;
const pirs = pirService as unknown as Record<string, ReturnType<typeof vi.fn>>;
const incidents = incidentService as unknown as Record<string, ReturnType<typeof vi.fn>>;

beforeEach(() => {
  vi.resetAllMocks();
  releases.list.mockResolvedValue({
    rows: [{ id: 7, name: 'Release 24.3' }, { id: 8, name: 'Release 24.2' }], total: 2,
  });
  pirs.getForRelease.mockResolvedValue(null);
});

const open = (props = {}) => render(
  <LinkIncidentToPirDialog open incidentId={41} defaultReleaseId={7}
                           onClose={() => {}} onLinked={() => {}} {...props} />,
);

describe('LinkIncidentToPirDialog', () => {
  it('asks the server for releases that have gone live', async () => {
    open();
    await waitFor(() => expect(releases.list).toHaveBeenCalledWith(
      expect.objectContaining({ implemented: true })));
  });

  it('never offers to create a release, and never mentions a fix release', async () => {
    open();
    await screen.findByLabelText(/release/i);
    expect(screen.queryByText(/create.*release/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/fix release/i)).not.toBeInTheDocument();
  });

  it('preselects the causal release when it is one of the live ones', async () => {
    open();
    expect(await screen.findByDisplayValue('Release 24.3')).toBeInTheDocument();
  });

  it('preselects nothing when the causal release has not gone live', async () => {
    // And, the half that matters: with nothing selected the dialog cannot be
    // submitted. Holding the default id while showing an empty picker would let
    // someone cite a release they never saw — which is what the display
    // assertions alone cannot see, since an id with no matching option renders
    // as empty either way.
    releases.list.mockResolvedValue({ rows: [{ id: 8, name: 'Release 24.2' }], total: 1 });
    open({ defaultReleaseId: 7 });
    await screen.findByLabelText(/release/i);
    expect(screen.queryByDisplayValue('Release 24.3')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Release 24.2')).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/what went wrong/i), 'No load test');
    expect(screen.getByRole('button', { name: /^link$/i })).toBeDisabled();
  });

  it('creates a PIR, a finding and an action in one call when the release has none',
    async () => {
      incidents.citeOnPir.mockResolvedValue([]);
      open();
      await screen.findByDisplayValue('Release 24.3');
      await userEvent.type(screen.getByLabelText(/what went wrong/i), 'No load test');
      await userEvent.type(screen.getByLabelText(/root cause/i), 'Gate optional');
      await userEvent.type(screen.getByLabelText(/first action/i), 'Make the gate mandatory');
      await userEvent.click(screen.getByRole('button', { name: /^link$/i }));
      await waitFor(() => expect(incidents.citeOnPir).toHaveBeenCalledWith(41, {
        release_id: 7,
        new_finding: {
          title: 'No load test', detail: null, root_cause: 'Gate optional',
          actions: [{ title: 'Make the gate mandatory' }],
        },
        note: null,
      }));
    });

  it('sends no actions when the optional first action is left blank', async () => {
    // `actions: [{ title: '' }]` would create an untitled action the server has
    // to refuse — the empty field means "none", not "one with no name".
    incidents.citeOnPir.mockResolvedValue([]);
    open();
    await screen.findByDisplayValue('Release 24.3');
    await userEvent.type(screen.getByLabelText(/what went wrong/i), 'No load test');
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }));
    await waitFor(() => expect(incidents.citeOnPir).toHaveBeenCalled());
    expect(incidents.citeOnPir.mock.calls[0][1].new_finding.actions).toEqual([]);
  });

  it('does not warn that the release has no PIR — one is created as part of linking',
    async () => {
      open();
      await screen.findByDisplayValue('Release 24.3');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

  it("offers that release's went-wrong findings when it already has a PIR", async () => {
    pirs.getForRelease.mockResolvedValue({
      id: 1, release_id: 7, summary: null, status: 'draft', completed_at: null,
      findings: [
        { id: 10, kind: 'went_well', seq: 1, title: 'Canary caught it', detail: null,
          root_cause: null, created_at: '', actions: [], incidents: [] },
        { id: 11, kind: 'went_wrong', seq: 1, title: 'No load test', detail: null,
          root_cause: null, created_at: '', actions: [], incidents: [] },
      ],
    });
    incidents.citeOnPir.mockResolvedValue([]);
    open();
    await userEvent.click(await screen.findByRole('radio', { name: /existing finding/i }));
    await userEvent.click(screen.getByLabelText(/^finding$/i));
    // Only the went-wrong finding: an incident is evidence something went WRONG,
    // and citing it against a "keep doing this" item would file a production
    // failure in the good column.
    expect(await screen.findByRole('option', { name: /No load test/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Canary caught it/ })).not.toBeInTheDocument();
  });

  it('cites the chosen existing finding by id, sending no new_finding', async () => {
    pirs.getForRelease.mockResolvedValue({
      id: 1, release_id: 7, summary: null, status: 'draft', completed_at: null,
      findings: [
        { id: 11, kind: 'went_wrong', seq: 1, title: 'No load test', detail: null,
          root_cause: null, created_at: '', actions: [], incidents: [] },
      ],
    });
    incidents.citeOnPir.mockResolvedValue([]);
    open();
    await userEvent.click(await screen.findByRole('radio', { name: /existing finding/i }));
    await userEvent.click(screen.getByLabelText(/^finding$/i));
    await userEvent.click(await screen.findByRole('option', { name: /No load test/ }));
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }));
    // Exactly one of the two: both is a 422, and guessing which was meant is how
    // a citation lands on the wrong review.
    await waitFor(() => expect(incidents.citeOnPir).toHaveBeenCalledWith(41, {
      release_id: 7, finding_id: 11, note: null,
    }));
  });

  it('shows the server error text, not an HTTP status', async () => {
    incidents.citeOnPir.mockRejectedValue({
      isAxiosError: true,
      response: {
        status: 422,
        data: { detail: 'supply exactly one of finding_id or new_finding' },
      },
      message: 'Request failed with status code 422',
    });
    open();
    await screen.findByDisplayValue('Release 24.3');
    await userEvent.type(screen.getByLabelText(/what went wrong/i), 'T');
    await userEvent.click(screen.getByRole('button', { name: /^link$/i }));
    expect(await screen.findByText(/supply exactly one/i)).toBeInTheDocument();
  });
});

// ── The panel on the incident page itself ────────────────────────────────────
//
// The dialog tests above cover what is SENT. These cover what is SHOWN, and in
// particular the two things this task exists to remove: a button that waited for
// a fix release, and copy that told the user to go and link one.

describe('IncidentDetail — the PIR panel', () => {
  const citation = {
    pir_id: 1, release_id: 7, release_name: 'Release 24.3', pir_status: 'draft' as const,
    finding_id: 11, finding_title: 'No load test', root_cause: 'Gate optional',
    note: null, action_count: 2, open_action_count: 1,
  };

  const detail = (overrides: Record<string, unknown> = {}) => ({
    id: 41, title: 'Checkout 500s', description: null, severity: 'P1', status: 'new',
    detected_at: '2026-08-01T00:00:00Z', resolved_at: null, source: 'manual',
    external_ref: null, environment_id: null, environment_name: null, deployment_id: null,
    release_id: 7, release: null,
    // The whole point: NO fix release, and the control is still live.
    fix_release_id: null, fix_release: null, fix_release_changes_by_epic: {},
    system_id: null, system_name: null, subsystem_id: null, subsystem_name: null,
    custom_fields: null, allowed_transitions: [], status_history: [],
    pir_citations: [citation],
    ...overrides,
  });

  const renderDetail = async (body: Record<string, unknown>) => {
    const { default: IncidentDetail } = await import('../IncidentDetail');
    const { default: incidentReducer } = await import('../../../store/incidentSlice');
    const { configureStore } = await import('@reduxjs/toolkit');
    const { Provider } = await import('react-redux');
    const { MemoryRouter, Route, Routes } = await import('react-router-dom');
    const { SnackbarProvider } = await import('notistack');

    const store = configureStore({
      reducer: { incident: incidentReducer },
      preloadedState: {
        incident: {
          list: [], total: 0, detail: body, loading: false, listLoading: false, error: null,
        },
      },
    } as Parameters<typeof configureStore>[0]);
    return render(
      <Provider store={store}>
        <SnackbarProvider>
          <MemoryRouter initialEntries={['/incidents/41']}>
            <Routes>
              <Route path="/incidents/:id" element={<IncidentDetail />} />
            </Routes>
          </MemoryRouter>
        </SnackbarProvider>
      </Provider>,
    );
  };

  it('lists citations by release and finding name', async () => {
    await renderDetail(detail());
    const link = await screen.findByRole('link', { name: 'Release 24.3' });
    expect(link).toHaveAttribute('href', '/releases/7');
    expect(screen.getByText(/No load test/)).toBeInTheDocument();
    expect(screen.getByText(/Gate optional/)).toBeInTheDocument();
  });

  it('shows how many process actions are still open', async () => {
    await renderDetail(detail());
    expect(await screen.findByText(/1 of 2 process actions still open/)).toBeInTheDocument();
  });

  it('offers Link to a PIR with no fix release, and never disables it', async () => {
    await renderDetail(detail());
    const button = await screen.findByRole('button', { name: /link to a pir/i });
    expect(button).toBeEnabled();
    // The old dead end, in both its parts.
    expect(screen.queryByRole('button', { name: /create pir/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/link a fix release/i)).not.toBeInTheDocument();
  });

  it('says plainly that no review cites this incident yet, without calling it a gap',
    async () => {
      await renderDetail(detail({ pir_citations: [] }));
      expect(await screen.findByText(/no review cites this incident yet/i)).toBeInTheDocument();
      // An uncited incident is an ordinary state, not something to close.
      expect(screen.queryByText(/gap|missing|required|outstanding/i)).not.toBeInTheDocument();
      expect(screen.getByRole('button', { name: /link to a pir/i })).toBeEnabled();
    });
});
