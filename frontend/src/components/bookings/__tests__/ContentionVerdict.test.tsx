/**
 * `ContentionVerdict` — what A4 says about one conflicting pair, and the ask.
 *
 * THREE THINGS THIS FILE EXISTS TO PIN, all of them rules A4 can only break
 * silently:
 *
 *  1. **A4 ADVISES; IT NEVER ACTS.** Nothing here may disable, gate or hide a
 *     booking action, and no copy may read as "you cannot proceed until this is
 *     resolved". An Escalate control is an ask, not a gate.
 *  2. **THREE OF THE FOUR OUTCOMES HAVE NO WINNER**, each carrying its own
 *     `reason` from the server. The screen renders THAT string — it does not
 *     compose an explanation of its own, and it never invents a winner.
 *  3. **Entities render by name.** A `ranked` verdict names the winning
 *     PROJECT; the pair's project names travel on the response for exactly
 *     this, because `winner_booking_id` is an integer and
 *     `other_booking.project_name` is the request's free-text "Purpose", not
 *     the linked project.
 *
 * The failure paths reject with a genuine **AxiosError shape** (`response.data.detail`),
 * never a pre-formatted `Error` carrying the final text: there is no
 * rejectWithValue boundary in front of `contentionService`, so the component's
 * own catch must call `formatApiError`, and a plain `Error` fixture passes
 * while the app shows "Request failed with status code 409".
 *
 * And it RE-RENDERS with changed props rather than only mounting — two A2
 * defects needed a second render to surface, and mount-only tests missed both.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { EnvBookingSummary } from '../../../types/bookingRequest';
import type { Contention, Escalation } from '../../../types/contention';

vi.mock('../../../services/contentionService', () => ({
  contentionService: { escalate: vi.fn(), decide: vi.fn(), list: vi.fn() },
}));

// The owner picker reads GET /tenant/users/lite straight through `api`,
// matching GatesTable.tsx and EnvironmentDetail's owner picker.
vi.mock('../../../services/api', () => ({
  default: { get: vi.fn() },
}));

import api from '../../../services/api';
import { contentionService } from '../../../services/contentionService';
import ContentionVerdict from '../ContentionVerdict';

const SUBJECT_ID = 7301;
const OTHER_ID = 7302;
const OWNER_ID = 4102;
const OWNER = 'release-manager';

/** An AxiosError, near enough: what `formatApiError` actually has to unwrap. */
const axiosError = (status: number, detail: string) => ({
  isAxiosError: true,
  name: 'AxiosError',
  message: `Request failed with status code ${status}`,
  response: { status, data: { detail } },
});

function otherBooking(overrides: Partial<EnvBookingSummary> = {}): EnvBookingSummary {
  return {
    id: OTHER_ID,
    environment_id: 55,
    environment_name: 'Staging',
    // The free-text "Purpose" on the request — deliberately NOT a project name,
    // and deliberately something no verdict line may ever pick up by mistake.
    project_name: 'Regression sweep',
    start_date: '2026-09-01T09:00:00Z',
    end_date: '2026-09-03T17:00:00Z',
    status: 'approved',
    has_unacknowledged_conflicts: false,
    agreement_gap: null,
    has_unacknowledged_agreement_gap: false,
    environment_group_id: null,
    environment_group_name: null,
    ...overrides,
  };
}

function contention(overrides: Partial<Contention> = {}): Contention {
  return {
    outcome: 'ranked',
    winner_booking_id: SUBJECT_ID,
    reason: 'the higher-priority project wins',
    escalation: null,
    booking_project_name: 'Mortgage Replatform',
    other_project_name: 'Payments Rebuild',
    ...overrides,
  };
}

function escalation(overrides: Partial<Escalation> = {}): Escalation {
  return {
    id: 901,
    booking_id: SUBJECT_ID,
    other_booking_id: OTHER_ID,
    owner_user_id: OWNER_ID,
    owner_username: OWNER,
    escalated_by: 4101,
    escalated_by_username: 'alice',
    respond_by: '2026-09-15T00:00:00Z',
    state: 'open',
    bookings_live: true,
    booking_environment_name: 'Staging',
    booking_project_name: 'Mortgage Replatform',
    other_booking_environment_name: 'Staging',
    other_booking_project_name: 'Payments Rebuild',
    // Neither side is a group booking by default; the group note on this
    // panel is driven by `subjectGroupName` / `environment_group_name`, and
    // these two carry the same fact for the WORKLIST's rows.
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

const onEscalated = vi.fn();

function renderVerdict(props: Partial<Parameters<typeof ContentionVerdict>[0]> = {}) {
  const merged = {
    bookingId: SUBJECT_ID,
    otherBooking: otherBooking(),
    contention: contention(),
    subjectGroupName: null,
    canEscalate: true,
    onEscalated,
    ...props,
  };
  const view = render(
    <MemoryRouter>
      <ContentionVerdict {...merged} />
    </MemoryRouter>
  );
  return {
    ...view,
    rerenderWith: (next: Partial<typeof merged>) =>
      view.rerender(
        <MemoryRouter>
          <ContentionVerdict {...merged} {...next} />
        </MemoryRouter>
      ),
  };
}

beforeEach(() => {
  vi.mocked(contentionService.escalate).mockReset();
  vi.mocked(api.get).mockReset().mockResolvedValue({
    data: [{ id: OWNER_ID, username: OWNER }],
  });
  onEscalated.mockReset();
});

describe('the verdict line', () => {
  it('names the winning project and the one it outranks, never an id', async () => {
    renderVerdict();

    const line = await screen.findByTestId('contention-verdict');
    expect(line).toHaveTextContent(/Mortgage Replatform/);
    expect(line).toHaveTextContent(/outranks/i);
    expect(line).toHaveTextContent(/Payments Rebuild/);
    // Neither booking id anywhere in it, and not the free-text Purpose either —
    // "Regression sweep" is `BookingRequest.project_name`, which is exactly the
    // field a verdict line must not mistake for the project.
    expect(line.textContent).not.toContain(String(SUBJECT_ID));
    expect(line.textContent).not.toContain(String(OTHER_ID));
    expect(line.textContent).not.toContain('Regression sweep');
  });

  it('names the OTHER project as the winner when the other booking won', async () => {
    // Same pair, other side wins. A line that hardcoded "this booking's project
    // wins" — the only naming a frontend could do before the names travelled on
    // the response — reads exactly backwards here.
    renderVerdict({
      contention: contention({ winner_booking_id: OTHER_ID }),
    });

    const line = await screen.findByTestId('contention-verdict');
    expect(line.textContent).toMatch(/Payments Rebuild\b.*outranks.*Mortgage Replatform/i);
  });

  it.each([
    ['no_project', 'at least one booking is not linked to a project'],
    [
      'no_project',
      "at least one booking's project is archived or belongs to another tenant",
    ],
    ['unranked', 'at least one project has no priority rank'],
    ['equal_rank', 'both projects have the same priority rank'],
  ])('renders the server reason verbatim for %s and invents no winner', async (outcome, reason) => {
    renderVerdict({
      contention: contention({
        outcome: outcome as Contention['outcome'],
        winner_booking_id: null,
        reason,
      }),
    });

    const line = await screen.findByTestId('contention-verdict');
    expect(line).toHaveTextContent(reason);
    // No fabricated ordering anywhere on the line.
    expect(line.textContent).not.toMatch(/outranks/i);
  });

  it('still names an archived project beside the reason that explains it', async () => {
    // The case `REASON_PROJECT_UNRESOLVABLE` exists for: the verdict says the
    // link cannot be resolved AND the name is on screen, because
    // `get_project_names` deliberately does not filter `deleted_at`. Told "not
    // linked to a project" while looking at the project's name, a user reads
    // the register as broken.
    renderVerdict({
      contention: contention({
        outcome: 'no_project',
        winner_booking_id: null,
        reason: "at least one booking's project is archived or belongs to another tenant",
      }),
    });

    const panel = await screen.findByTestId('contention-panel');
    expect(panel).toHaveTextContent('Mortgage Replatform');
    expect(panel).toHaveTextContent('Payments Rebuild');
  });

  it('says nothing about a project it has no name for', async () => {
    // Null is a real state — no project — not a missing value, so nothing
    // fabricates a label and `#N` never appears.
    renderVerdict({
      contention: contention({
        outcome: 'no_project',
        winner_booking_id: null,
        reason: 'at least one booking is not linked to a project',
        booking_project_name: null,
        other_project_name: 'Payments Rebuild',
      }),
    });

    const panel = await screen.findByTestId('contention-panel');
    expect(panel.textContent).not.toContain(`#${SUBJECT_ID}`);
    expect(panel.textContent).not.toMatch(/Booking #/);
  });
});

describe('the group note', () => {
  it('says when the booking that would give way is one of a group', async () => {
    // A2's atomic transition moves EVERY member of the group. Without this the
    // line reads as "move this one booking", which is not what would happen.
    renderVerdict({
      contention: contention({ winner_booking_id: SUBJECT_ID }),
      otherBooking: otherBooking({
        environment_group_id: 12,
        environment_group_name: 'Payments Suite',
      }),
    });

    const note = await screen.findByTestId('contention-group-note');
    expect(note).toHaveTextContent('Payments Suite');
    expect(note.textContent).toMatch(/every environment|whole group|all .* members/i);
  });

  it("names the SUBJECT's group when the subject is the booking that gives way", async () => {
    renderVerdict({
      contention: contention({ winner_booking_id: OTHER_ID }),
      subjectGroupName: 'Mortgage Suite',
    });

    expect(await screen.findByTestId('contention-group-note')).toHaveTextContent(
      'Mortgage Suite'
    );
  });

  it('says nothing about groups when the decision names no booking', async () => {
    // A no-winner outcome names nobody, so there is nothing to warn about —
    // and a group note beside "priority does not separate these" reads as a
    // consequence that is not being claimed.
    renderVerdict({
      contention: contention({
        outcome: 'equal_rank',
        winner_booking_id: null,
        reason: 'both projects have the same priority rank',
      }),
      otherBooking: otherBooking({
        environment_group_id: 12,
        environment_group_name: 'Payments Suite',
      }),
    });

    await screen.findByTestId('contention-verdict');
    expect(screen.queryByTestId('contention-group-note')).not.toBeInTheDocument();
  });
});

describe('escalating', () => {
  it('offers an Escalate control and defaults the deadline three WORKING days ahead', async () => {
    const user = userEvent.setup();
    // A Wednesday: three calendar days would be Saturday, three working days is
    // the following Monday.
    vi.setSystemTime(new Date('2026-08-05T11:00:00Z'));
    renderVerdict();

    await user.click(await screen.findByRole('button', { name: /Escalate/i }));

    const respondBy = await screen.findByLabelText(/Respond by/i);
    expect(respondBy).toHaveValue('2026-08-10');
    vi.useRealTimers();
  });

  it('counts those three days from the READER\'s day, not from UTC\'s', async () => {
    // THE DEFAULT IS SEEDED WITH AN INSTANT AND COUNTED IN UTC, so the two have
    // to be reconciled at the call site. Under TZ=UTC they are identical, which
    // is why this test sets a real one: at 08:00 on Wednesday in Auckland it is
    // still Tuesday in UTC, and counting from Tuesday hands the named owner a
    // deadline one working day earlier than the field's own helper text
    // promises. The test above cannot see this — every clock it uses is a UTC
    // midday.
    vi.stubEnv('TZ', 'Pacific/Auckland');
    try {
      const user = userEvent.setup();
      // Wednesday 12 August, 08:00 in Auckland — Tuesday 11th, 20:00Z.
      vi.setSystemTime(new Date('2026-08-11T20:00:00Z'));
      renderVerdict();

      await user.click(await screen.findByRole('button', { name: /Escalate/i }));

      // Wednesday + Thu, Fri, Mon. Counted from the UTC instant it would read
      // 2026-08-14.
      expect(await screen.findByLabelText(/Respond by/i)).toHaveValue('2026-08-17');
    } finally {
      vi.useRealTimers();
      vi.unstubAllEnvs();
    }
  });

  it('posts the owner and the deadline the escalator chose, and tells its parent', async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.escalate).mockResolvedValue(escalation());
    renderVerdict();

    await user.click(await screen.findByRole('button', { name: /Escalate/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox', { name: 'Decision owner' }));
    await user.click(await screen.findByRole('option', { name: OWNER }));
    const respondBy = within(dialog).getByLabelText(/Respond by/i);
    await user.clear(respondBy);
    await user.type(respondBy, '2026-09-15');
    await user.click(within(dialog).getByRole('button', { name: /^Escalate$/i }));

    await waitFor(() =>
      expect(contentionService.escalate).toHaveBeenCalledWith(SUBJECT_ID, OTHER_ID, {
        owner_user_id: OWNER_ID,
        respond_by: '2026-09-15T00:00:00Z',
      })
    );
    // The parent reloads: the escalation is now part of the conflicts payload.
    await waitFor(() => expect(onEscalated).toHaveBeenCalled());
  });

  it("shows the SERVER's reason when escalating is refused", async () => {
    const user = userEvent.setup();
    vi.mocked(contentionService.escalate).mockRejectedValue(
      axiosError(400, 'These two bookings are not in conflict, so there is nothing to escalate')
    );
    renderVerdict();

    await user.click(await screen.findByRole('button', { name: /Escalate/i }));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('combobox', { name: 'Decision owner' }));
    await user.click(await screen.findByRole('option', { name: OWNER }));
    await user.click(within(dialog).getByRole('button', { name: /^Escalate$/i }));

    expect(
      await screen.findByText(
        'These two bookings are not in conflict, so there is nothing to escalate'
      )
    ).toBeInTheDocument();
    // Not the generic Axios message, which is what a component reading
    // `err.message` would render.
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });

  it('offers no Escalate control to someone with no part in either booking', async () => {
    renderVerdict({ canEscalate: false });

    await screen.findByTestId('contention-verdict');
    expect(screen.queryByRole('button', { name: /Escalate/i })).not.toBeInTheDocument();
  });
});

describe('an escalation that already exists', () => {
  it('shows who must decide, by when, who asked, and the state', async () => {
    renderVerdict({ contention: contention({ escalation: escalation() }) });

    const panel = await screen.findByTestId('contention-escalation');
    expect(panel).toHaveTextContent(OWNER);
    expect(panel).toHaveTextContent('alice');
    expect(panel).toHaveTextContent(new Date('2026-09-15T00:00:00Z').toLocaleDateString());
    expect(panel).toHaveTextContent(/open/i);
    // One escalation per contention — asking again is not on offer.
    expect(screen.queryByRole('button', { name: /Escalate/i })).not.toBeInTheDocument();
  });

  it('reads as expired with no refresh, because the server computed it', async () => {
    renderVerdict({
      contention: contention({
        escalation: escalation({ state: 'expired', respond_by: '2026-01-05T00:00:00Z' }),
      }),
    });

    expect(await screen.findByTestId('contention-escalation')).toHaveTextContent(/expired/i);
  });

  it('trusts the server over the deadline it can see', async () => {
    // `state` is computed server-side from two columns and a clock, and the
    // browser must NOT re-derive it from `respond_by`. A deadline in the past
    // with `state: 'open'` is the case that tells the two apart: it happens
    // whenever the client clock is off, and re-deriving would show a queue of
    // phantom expiries nobody can clear.
    renderVerdict({
      contention: contention({
        escalation: escalation({ state: 'open', respond_by: '2020-01-01T00:00:00Z' }),
      }),
    });

    const panel = await screen.findByTestId('contention-escalation');
    expect(panel).toHaveTextContent(/open/i);
    expect(panel.textContent).not.toMatch(/expired/i);
  });

  it('reports an answered escalation by naming the booking that gives way', async () => {
    renderVerdict({
      contention: contention({
        escalation: escalation({
          state: 'answered',
          decision_yields_booking_id: OTHER_ID,
          decision_notes: 'Payments can slip a week',
          decided_by: OWNER_ID,
          decided_by_username: OWNER,
          decided_at: '2026-09-10T14:00:00Z',
        }),
      }),
    });

    const panel = await screen.findByTestId('contention-escalation');
    expect(panel).toHaveTextContent('Payments Rebuild');
    expect(panel).toHaveTextContent('Payments can slip a week');
    expect(panel).toHaveTextContent(OWNER);
  });

  it('says when the contention has gone away without deleting the record', async () => {
    renderVerdict({
      contention: contention({ escalation: escalation({ bookings_live: false }) }),
    });

    const panel = await screen.findByTestId('contention-escalation');
    expect(panel).toHaveTextContent(/no longer live/i);
    // The trail is still there — the ask and its owner remain readable.
    expect(panel).toHaveTextContent(OWNER);
  });
});

describe('re-rendering with different props', () => {
  it('drops the previous verdict when the new conflict has a different one', async () => {
    const { rerenderWith } = renderVerdict();
    expect(await screen.findByTestId('contention-verdict')).toHaveTextContent(
      /Mortgage Replatform/
    );

    rerenderWith({
      contention: contention({
        outcome: 'unranked',
        winner_booking_id: null,
        reason: 'at least one project has no priority rank',
        booking_project_name: 'Ledger Migration',
        other_project_name: 'Payments Rebuild',
      }),
    });

    const line = await screen.findByTestId('contention-verdict');
    expect(line).toHaveTextContent('at least one project has no priority rank');
    expect(line.textContent).not.toMatch(/outranks/i);
    expect(line.textContent).not.toContain('Mortgage Replatform');
  });

  it('drops an escalation that the new conflict does not have', async () => {
    const { rerenderWith } = renderVerdict({
      contention: contention({ escalation: escalation() }),
    });
    expect(await screen.findByTestId('contention-escalation')).toHaveTextContent(OWNER);

    rerenderWith({ contention: contention({ escalation: null }) });

    await waitFor(() =>
      expect(screen.queryByTestId('contention-escalation')).not.toBeInTheDocument()
    );
    // …and the ask is on offer again, because this pair has never been escalated.
    expect(screen.getByRole('button', { name: /Escalate/i })).toBeInTheDocument();
  });
});

describe('A4 advises; it never acts', () => {
  it('disables nothing and claims to prevent nothing, on every outcome', async () => {
    for (const c of [
      contention(),
      contention({ outcome: 'unranked', winner_booking_id: null, reason: 'r' }),
      contention({ escalation: escalation({ state: 'expired' }) }),
      contention({ escalation: escalation({ state: 'open' }) }),
    ]) {
      const { unmount } = renderVerdict({ contention: c });
      const panel = await screen.findByTestId('contention-panel');
      expect(panel.textContent).not.toMatch(
        /cannot proceed|not allowed|blocked|must be resolved|before you can/i
      );
      panel.querySelectorAll('button').forEach((b) => expect(b).not.toBeDisabled());
      unmount();
    }
  });
});
