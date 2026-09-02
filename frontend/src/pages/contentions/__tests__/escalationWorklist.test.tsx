/**
 * The escalation worklist — what a named owner opens to see what they must
 * decide.
 *
 * A WORKLIST IS A LIST OF THINGS THE READER HAS NEVER SEEN, which is why every
 * row is identified by the environment and the two projects rather than by
 * `booking_id` / `other_booking_id`. Two integers say nothing about which
 * argument a row is, and `Booking #12` is exactly the `#N` fallback this
 * codebase has a standing rule against. The names travel on the response,
 * batched server-side, for the same reason the usernames do.
 *
 * A4 ADVISES; IT NEVER ACTS. Recording a decision writes four columns on the
 * escalation and moves nothing: no booking is transitioned, rejected or
 * rescheduled by anything on this page, and the copy says so.
 *
 * The failure path rejects with a genuine **AxiosError shape**, never a
 * pre-formatted `Error`: `contentionService.decide` has no slice thunk in front
 * of it, so this page's own catch must call `formatApiError`.
 */
import type { ReactNode } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { store } from '../../../store';
import { setCredentials } from '../../../store/authSlice';
import type { Escalation } from '../../../types/contention';

vi.mock('../../../services/contentionService', () => ({
  contentionService: { list: vi.fn(), decide: vi.fn(), escalate: vi.fn() },
}));

// jsdom reports a zero-width container, so the real DataGrid mounts almost no
// cells. This unvirtualized stand-in renders every column's cell for every row
// through the column's own renderCell/valueGetter, and captures the props the
// page passed — needed for the `disableColumnFilter` / server-mode assertions,
// which have no DOM form.
const { capturedGridProps } = vi.hoisted(() => ({
  capturedGridProps: { current: undefined as Record<string, unknown> | undefined },
}));

vi.mock('@mui/x-data-grid', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mui/x-data-grid')>();
  return {
    ...actual,
    DataGrid: (props: Record<string, unknown>) => {
      capturedGridProps.current = props;
      const rows = props.rows as Array<Record<string, unknown>>;
      const columns = props.columns as Array<{
        field: string;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        renderCell?: (params: any) => ReactNode;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        valueGetter?: (params: any) => unknown;
      }>;
      return (
        <table>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.id)} data-testid={`row-${row.id}`}>
                {columns.map((col) => (
                  <td key={col.field}>
                    {col.renderCell
                      ? col.renderCell({ row, value: row[col.field], id: row.id })
                      : col.valueGetter
                        ? String(col.valueGetter({ row }))
                        : String(row[col.field] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  };
});

import { contentionService } from '../../../services/contentionService';
import EscalationWorklist from '../EscalationWorklist';

const ME = 6101;
const OTHER_PERSON = 6102;

const axiosError = (status: number, detail: string) => ({
  isAxiosError: true,
  name: 'AxiosError',
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail } },
});

function escalation(overrides: Partial<Escalation> = {}): Escalation {
  return {
    id: 101,
    booking_id: 8001,
    other_booking_id: 8002,
    owner_user_id: ME,
    owner_username: 'release-manager',
    escalated_by: 6109,
    escalated_by_username: 'alice',
    respond_by: '2026-09-15T00:00:00Z',
    state: 'open',
    bookings_live: true,
    booking_environment_name: 'Staging',
    booking_project_name: 'Mortgage Replatform',
    other_booking_environment_name: 'Staging',
    other_booking_project_name: 'Payments Rebuild',
    // The ordinary case — neither side is a group booking. The tests that care
    // override one side only, so a site filling both from one lookup, or
    // hedging in general instead of naming this row's group, cannot pass.
    booking_group_name: null,
    other_booking_group_name: null,
    decision_yields_booking_id: null,
    decision_notes: null,
    decided_by: null,
    decided_by_username: null,
    decided_at: null,
    ...overrides,
  };
}

function signIn(id: number, role = 'Developer') {
  store.dispatch(
    setCredentials({
      user: {
        id,
        username: `user-${id}`,
        email: `user-${id}@test.com`,
        role,
        tenant_id: 1,
        is_active: true,
        is_master_admin: false,
      } as never,
      token: 'test-token',
    })
  );
}

function renderPage(initialEntry = '/contentions') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <EscalationWorklist />
      </MemoryRouter>
    </Provider>
  );
}

beforeEach(() => {
  capturedGridProps.current = undefined;
  vi.mocked(contentionService.list)
    .mockReset()
    .mockResolvedValue({ rows: [escalation()], total: 1 });
  vi.mocked(contentionService.decide).mockReset();
  signIn(ME);
});

describe('the worklist', () => {
  it('identifies each row by environment and by both projects, never by id', async () => {
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent('Staging');
    expect(row).toHaveTextContent('Mortgage Replatform');
    expect(row).toHaveTextContent('Payments Rebuild');
    expect(row.textContent).not.toMatch(/#\s*800[12]/);
    expect(row.textContent).not.toMatch(/Booking #/);
  });

  it('shows who must decide, by when, and the state the server computed', async () => {
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent('release-manager');
    expect(row).toHaveTextContent(new Date('2026-09-15T00:00:00Z').toLocaleDateString());
    expect(row).toHaveTextContent(/open/i);
  });

  it('reads an expired row as expired without re-deriving it from the deadline', async () => {
    // `state` is computed server-side from two columns and a clock. A row whose
    // deadline has passed but which the server still calls `open` must read as
    // open: re-deriving in the browser turns a wrong client clock into a queue
    // of phantom expiries.
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [
        escalation({ id: 101, state: 'expired', respond_by: '2026-01-01T00:00:00Z' }),
        escalation({ id: 102, state: 'open', respond_by: '2020-01-01T00:00:00Z' }),
      ],
      total: 2,
    });
    renderPage();

    expect(await screen.findByTestId('row-101')).toHaveTextContent(/expired/i);
    const stillOpen = screen.getByTestId('row-102');
    expect(stillOpen).toHaveTextContent(/open/i);
    expect(stillOpen.textContent).not.toMatch(/expired/i);
  });

  it('filters by state in the request, not in the browser', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: 'Open' }));

    await waitFor(() =>
      expect(contentionService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'open' })
      )
    );
  });

  it('sends no state at all for "All" — omission is the sentinel, not a value', async () => {
    // `GET /contention-escalations` deliberately has no `all` value on the
    // wire: `buildParams` drops a filter whose value is its own sentinel, so a
    // vocabulary containing `all` builds byte-identical params for two
    // different filter states and the grid never refetches.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-101');
    await user.click(screen.getByRole('button', { name: 'Answered' }));
    await waitFor(() =>
      expect(contentionService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'answered' })
      )
    );

    await user.click(screen.getByRole('button', { name: 'All' }));

    await waitFor(() => {
      const calls = vi.mocked(contentionService.list).mock.calls;
      const last = calls[calls.length - 1]?.[0];
      expect(last).not.toHaveProperty('state');
    });
  });

  it('opens on the soonest deadline, sorted and paged by the server', async () => {
    renderPage();
    await screen.findByTestId('row-101');

    expect(contentionService.list).toHaveBeenCalledWith(
      expect.objectContaining({ sort_by: 'respond_by', sort_dir: 'asc' })
    );
    expect(capturedGridProps.current?.paginationMode).toBe('server');
    expect(capturedGridProps.current?.sortingMode).toBe('server');
    // `rows` is one windowed page, not the whole set — filtering it in the
    // browser would filter the page, not the result.
    expect(capturedGridProps.current?.disableColumnFilter).toBe(true);
  });

  it('offers no column the server would answer with a 422', async () => {
    // The contract in frontend/src/constants/sortWhitelists.json, asserted
    // against the grid rather than against a hand-written copy of itself.
    const { default: whitelists } = await import('../../../constants/sortWhitelists.json');
    renderPage();
    await screen.findByTestId('row-101');

    const columns = capturedGridProps.current?.columns as Array<{
      field: string;
      sortable?: boolean;
    }>;
    const sortable = whitelists['contention-escalations'].sortable;
    columns
      .filter((c) => c.sortable !== false)
      .forEach((c) => expect(sortable).toContain(c.field));
  });

  it('narrows the queue to the reader\'s own contentions, in the request', async () => {
    // THE FILTER THIS PAGE WAS BUILT FOR. Its purpose is "what a named owner
    // opens to see what they must decide", and everyone's queue is not that:
    // with sixty escalations in a tenant, the decider hunts their own username
    // down the *To decide* column. Sent as `owner_user_id` on the wire — a
    // browser-side narrowing would filter one windowed PAGE and leave the total
    // describing the whole set.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: 'Mine' }));

    await waitFor(() =>
      expect(contentionService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ owner_user_id: ME })
      )
    );
  });

  it('sends no owner at all for "Anyone" — omission is the sentinel', async () => {
    // Same rule as `state`: the wire has no "everyone" value, and the chip
    // vocabulary avoids `all` because that is `buildParams`' own "no selection"
    // sentinel — two chips building byte-identical params never refetch.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-101');
    await user.click(screen.getByRole('button', { name: 'Mine' }));
    await waitFor(() =>
      expect(contentionService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ owner_user_id: ME })
      )
    );

    await user.click(screen.getByRole('button', { name: 'Anyone' }));

    await waitFor(() => {
      const calls = vi.mocked(contentionService.list).mock.calls;
      const last = calls[calls.length - 1]?.[0];
      expect(last).not.toHaveProperty('owner_user_id');
    });
  });

  it('filters to the person actually signed in, not to a row on the page', async () => {
    // `owner_user_id` must come from the session, not from whatever the first
    // row happens to be assigned to: the reader's own queue is often EMPTY,
    // which is precisely when reading it off a row gives someone else's.
    const user = userEvent.setup();
    signIn(OTHER_PERSON);
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: 'Mine' }));

    await waitFor(() =>
      expect(contentionService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ owner_user_id: OTHER_PERSON })
      )
    );
    // Row 101's own owner is ME — reading the filter off the row would pass the
    // assertion above only by accident, so pin that it did not.
    const calls = vi.mocked(contentionService.list).mock.calls;
    expect(calls[calls.length - 1]?.[0]).not.toEqual(
      expect.objectContaining({ owner_user_id: ME })
    );
  });

  it('says when a row is no longer a live contention, and keeps the row', async () => {
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [escalation({ bookings_live: false })],
      total: 1,
    });
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent(/no longer live/i);
    // The audit trail survives its bookings — that is the point of storing it.
    expect(row).toHaveTextContent('release-manager');
  });
});

describe('recording a decision', () => {
  it('lets the named owner say which booking gives way, by name', async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.decide).mockResolvedValue(
      escalation({ state: 'answered', decision_yields_booking_id: 8002 })
    );
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: /Decide/i }));
    const dialog = await screen.findByRole('dialog');
    // The two sides are offered BY NAME — a radio labelled `8002` would be
    // unanswerable.
    await user.click(within(dialog).getByRole('radio', { name: /Payments Rebuild/ }));
    await user.type(within(dialog).getByLabelText(/Notes/i), 'Payments can slip a week');
    await user.click(within(dialog).getByRole('button', { name: /^Record decision$/i }));

    await waitFor(() =>
      expect(contentionService.decide).toHaveBeenCalledWith(101, {
        yields_booking_id: 8002,
        notes: 'Payments can slip a week',
      })
    );
    // Refetched — the row's state and decision are the server's answer.
    await waitFor(() => expect(contentionService.list).toHaveBeenCalledTimes(2));
  });

  it('sends notes: null for an empty box, which CLEARS a reason already on record', async () => {
    // `record_decision`'s documented contract: a second decision passing None
    // clears the first one's stated reason, because the row holds the decision
    // that stands and a reason carried over from a superseded one would be
    // attributed to the new decision. `notes: ''` would store an empty string
    // instead, which is a different thing on the wire and reads as "a reason
    // was given" to anything checking for null.
    const user = userEvent.setup();
    vi.mocked(contentionService.decide).mockResolvedValue(
      escalation({ state: 'answered', decision_yields_booking_id: 8002 })
    );
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: /Decide/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('radio', { name: /Payments Rebuild/ }));
    // Notes deliberately untouched.
    await user.click(within(dialog).getByRole('button', { name: /^Record decision$/i }));

    await waitFor(() =>
      expect(contentionService.decide).toHaveBeenCalledWith(101, {
        yields_booking_id: 8002,
        notes: null,
      })
    );
  });

  it("shows the SERVER's refusal when a decision is rejected", async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.decide).mockRejectedValue(
      axiosError(400, 'The yielding booking must be one of the two in contention')
    );
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: /Decide/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('radio', { name: /Payments Rebuild/ }));
    await user.click(within(dialog).getByRole('button', { name: /^Record decision$/i }));

    expect(
      await screen.findByText('The yielding booking must be one of the two in contention')
    ).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });

  it('offers no Decide control to somebody who is neither the owner nor an Admin', async () => {
    signIn(OTHER_PERSON);
    renderPage();

    await screen.findByTestId('row-101');
    expect(screen.queryByRole('button', { name: /Decide/i })).not.toBeInTheDocument();
  });

  it('offers Decide to an Admin who is not the named owner', async () => {
    // THE ESCAPE HATCH, and it must actually work in the UI. A4 ships no edit
    // and no withdraw path for an escalation, so a wrong owner or a deadline
    // that has passed can only be resolved by an Admin being able to answer.
    signIn(OTHER_PERSON, 'Admin');
    renderPage();

    await screen.findByTestId('row-101');
    expect(screen.getByRole('button', { name: /Decide/i })).toBeInTheDocument();
  });

  it('shows an answered row as answered, and offers no second ask', async () => {
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [
        escalation({
          state: 'answered',
          decision_yields_booking_id: 8002,
          decision_notes: 'Payments can slip a week',
          decided_by: ME,
          decided_by_username: 'release-manager',
          decided_at: '2026-09-10T14:00:00Z',
        }),
      ],
      total: 1,
    });
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent(/answered/i);
    expect(row).toHaveTextContent('Payments Rebuild');
    expect(row).toHaveTextContent('Payments can slip a week');
  });
});

describe('a side that is an A2 group booking', () => {
  // A GROUP BOOKING TRANSITIONS ALL-OR-NOTHING. So a decision naming one member
  // is a decision about every member, and this page — not the booking page — is
  // where the decision is actually made. An option reading "Payments Rebuild on
  // Staging" for one member of a five-environment group booking asks the reader
  // to choose a consequence nobody has told them about.

  it('names the environment group on the option that belongs to one', async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [escalation({ other_booking_group_name: 'Q3 Regression Suite' })],
      total: 1,
    });
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: /Decide/i }));
    const dialog = await screen.findByRole('dialog');

    // The group is named ON THE OPTION — it is part of the radio's accessible
    // name, so choosing it cannot be done without reading it.
    const grouped = within(dialog).getByRole('radio', { name: /Payments Rebuild/ });
    expect(grouped).toHaveAccessibleName(/Q3 Regression Suite/);
    expect(grouped).toHaveAccessibleName(/every environment/i);
    // …and NOT on the other side, which is not a group booking. A hedge
    // covering both options tells the reader nothing about either.
    expect(
      within(dialog).getByRole('radio', { name: /Mortgage Replatform/ })
    ).not.toHaveAccessibleName(/Q3 Regression Suite/);

    // An accessible name is satisfied equally by an aria-label with the real
    // text aria-hidden beside it — so the accessible-name checks above cannot
    // by themselves tell "visible caption" apart from "invisible attribute".
    // The whole point of this note is that a SIGHTED reader deciding between
    // the two radios can see it, so pin that the words are actually on the
    // page, not merely in the accessibility tree.
    expect(
      within(dialog).getByText(/every environment in Q3 Regression Suite/i)
    ).toBeVisible();
  });

  it('says nothing about groups when neither booking is in one', async () => {
    // The guard against replacing a per-row statement with a blanket one: the
    // majority of rows have no group, and a caution that fires on all of them
    // says nothing about the row in front of the reader.
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('row-101');

    await user.click(screen.getByRole('button', { name: /Decide/i }));
    const dialog = await screen.findByRole('dialog');

    expect(dialog.textContent).not.toMatch(/environment group|every environment|whole group/i);
  });

  it('names the group on a recorded decision, not just the one environment', async () => {
    // The Decision cell reads "<project> on <environment> gives way". For a
    // group booking that is one of five environments, and the row must say so.
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [
        escalation({
          state: 'answered',
          decision_yields_booking_id: 8002,
          other_booking_group_name: 'Q3 Regression Suite',
          decided_by: ME,
          decided_by_username: 'release-manager',
          decided_at: '2026-09-10T14:00:00Z',
        }),
      ],
      total: 1,
    });
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent('Payments Rebuild');
    expect(row).toHaveTextContent(/every environment in Q3 Regression Suite/i);
  });

  it('names the group of the side the decision actually names, never the other', async () => {
    // Both sides are group bookings and the decision names one of them. A cell
    // that read the group off the row rather than off the yielding side would
    // name the wrong group, confidently.
    vi.mocked(contentionService.list).mockResolvedValue({
      rows: [
        escalation({
          state: 'answered',
          decision_yields_booking_id: 8001,
          booking_group_name: 'Mortgage Cutover',
          other_booking_group_name: 'Q3 Regression Suite',
        }),
      ],
      total: 1,
    });
    renderPage();

    const row = await screen.findByTestId('row-101');
    expect(row).toHaveTextContent(/every environment in Mortgage Cutover/i);
    expect(row.textContent).not.toMatch(/every environment in Q3 Regression Suite/i);
  });
});

describe('reachability', () => {
  it('is routed in the real App and linked from the real nav', async () => {
    // A page nobody can navigate to is a page nobody has. The REAL files, not
    // fixtures — `?raw` is Vite's own primitive, the same technique
    // projectDetailGapLink.test.tsx uses, and deliberately not `node:fs`, which
    // works at runtime but fails `tsc --noEmit` in this package.
    const { default: appSource } = await import('../../../App.tsx?raw');
    const { appNav, isNavGroup } = await import('../../../components/navConfig');

    expect(appSource).toContain('path="/contentions"');
    expect(appSource).toContain('pages/contentions/EscalationWorklist');

    const paths = appNav.flatMap((entry) => (isNavGroup(entry) ? entry.children.map((c) => c.path) : [entry.path]));
    expect(paths).toContain('/contentions');
  });
});

describe('A4 advises; it never acts', () => {
  it('says on the page that recording a decision moves nothing', async () => {
    renderPage();
    await screen.findByTestId('row-101');

    // The page must not read as a queue of things that will happen by
    // themselves; acting on a decision stays with the owning team, and for an
    // A2 group booking that means the whole group transitions together.
    expect(screen.getByTestId('worklist-advisory')).toHaveTextContent(
      /nothing is moved|moves nothing|does not move/i
    );
  });
});
