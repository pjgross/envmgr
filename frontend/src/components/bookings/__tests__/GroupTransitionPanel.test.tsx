import type { ComponentProps } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import GroupTransitionPanel from '../GroupTransitionPanel';
import type { EnvBookingSummary } from '../../../types/bookingRequest';

// Task 9 — group transitions in the UI. The panel takes a group's members
// (already filtered by the caller) and renders ONE primary control set
// driven by the group endpoint's intersection, never a member's own
// allowed-transitions list — a button offered from a single member's list
// could be valid for it and refused for a sibling, which is exactly what the
// all-or-nothing transition exists to prevent.
//
// Final-review Finding 1: each member row ALSO gets its own link and its own
// individual-endpoint-driven transition control. That is deliberate and
// distinct from the primary control above — it is the only repair tool for a
// group that has gone out of step (see `outOfStep` below), and it has to be
// reachable right next to the divergence it repairs, per phase-7.md's
// explicit design trade ("forbidding it would convert a recoverable mess
// into a stuck one"). Every render in this file uses a real Router context
// (`MemoryRouter`) because of that link.

vi.mock('../../../services/environmentGroupService', () => ({
  environmentGroupService: {
    groupAllowedTransitions: vi.fn(),
    transitionGroup: vi.fn(),
  },
}));

// Mocked with a deliberately distinctive label so a test can tell "the
// group's own control" and "a member's own control" apart on screen without
// ambiguity.
vi.mock('../../../services/bookingService', () => ({
  bookingService: {
    getAllowedTransitions: vi.fn().mockResolvedValue([
      { from_state: 'submitted', to_state: 'approved', label: 'MEMBER-ONLY BUTTON' },
    ]),
    transitionState: vi.fn(),
    getBooking: vi.fn(),
  },
}));

import { environmentGroupService } from '../../../services/environmentGroupService';
import { bookingService } from '../../../services/bookingService';

// Deliberately distinct ids/names from every other fixture used elsewhere in
// the frontend test suite (bookingFormGroups.test.tsx uses env ids 501,
// group ids 601/602) so a wrong-data-source bug cannot pass by numeric or
// textual coincidence.
const REQUEST_ID = 7301;
const GROUP_ID = 7401;
const GROUP_NAME = 'Checkout Squad';

const MEMBER_A: EnvBookingSummary = {
  id: 7501,
  environment_id: 7601,
  environment_name: 'Checkout API',
  project_name: 'Regression sweep',
  start_date: '2026-08-10T09:00:00Z',
  end_date: '2026-08-11T09:00:00Z',
  status: 'submitted',
  environment_group_id: GROUP_ID,
  environment_group_name: GROUP_NAME,
};

const MEMBER_B: EnvBookingSummary = {
  id: 7502,
  environment_id: 7602,
  environment_name: 'Checkout DB',
  project_name: 'Regression sweep',
  start_date: '2026-08-10T09:00:00Z',
  end_date: '2026-08-11T09:00:00Z',
  status: 'submitted',
  environment_group_id: GROUP_ID,
  environment_group_name: GROUP_NAME,
};

const MEMBER_B_DRAFT: EnvBookingSummary = { ...MEMBER_B, status: 'draft' };

const GROUP_TRANSITIONS = [{ from_state: 'submitted', to_state: 'approved', label: 'Approve Group' }];

function renderPanel(props: Partial<ComponentProps<typeof GroupTransitionPanel>> = {}) {
  return render(
    <MemoryRouter>
      <GroupTransitionPanel
        requestId={REQUEST_ID}
        groupId={GROUP_ID}
        groupName={GROUP_NAME}
        bookings={[MEMBER_A, MEMBER_B]}
        {...props}
      />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.mocked(environmentGroupService.groupAllowedTransitions).mockReset().mockResolvedValue(GROUP_TRANSITIONS);
  vi.mocked(environmentGroupService.transitionGroup).mockReset();
  vi.mocked(bookingService.getAllowedTransitions)
    .mockReset()
    .mockResolvedValue([
      { from_state: 'submitted', to_state: 'approved', label: 'MEMBER-ONLY BUTTON' },
    ]);
});

describe('GroupTransitionPanel', () => {
  it("renders a group's members together under the group's name, each with its environment and current state", async () => {
    renderPanel();

    expect(await screen.findByText(`Group: ${GROUP_NAME}`)).toBeInTheDocument();
    expect(screen.getByText('Checkout API')).toBeInTheDocument();
    expect(screen.getByText('Checkout DB')).toBeInTheDocument();
    expect(screen.getAllByText('submitted')).toHaveLength(2);
  });

  it("drives the group's primary control from the group endpoint, and each member's own control from its individual endpoint", async () => {
    renderPanel();

    expect(await screen.findByRole('button', { name: 'Approve Group' })).toBeInTheDocument();
    expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledWith(
      REQUEST_ID,
      GROUP_ID
    );

    // Each member's own individual-endpoint control is the repair path
    // (Finding 1) — it is fetched per member id and rendered per row,
    // distinctly labelled here so it can't be confused with the group's own
    // "Approve Group" button above.
    expect(bookingService.getAllowedTransitions).toHaveBeenCalledWith(MEMBER_A.id);
    expect(bookingService.getAllowedTransitions).toHaveBeenCalledWith(MEMBER_B.id);
    expect(await screen.findAllByRole('button', { name: 'MEMBER-ONLY BUTTON' })).toHaveLength(2);
  });

  it('says members are out of step and names the environments, when their states differ', async () => {
    renderPanel({ bookings: [MEMBER_A, MEMBER_B_DRAFT] });

    const notice = await screen.findByText(/out of step/);
    expect(notice.textContent).toContain('Checkout API (submitted)');
    expect(notice.textContent).toContain('Checkout DB (draft)');
  });

  it('says nothing about being out of step when every member shares one state', async () => {
    renderPanel();

    await screen.findByText(`Group: ${GROUP_NAME}`);
    expect(screen.queryByText(/out of step/)).not.toBeInTheDocument();
  });

  it("renders the server's refusal message naming every failing member — AxiosError shape, no generic status text", async () => {
    // Shaped like a real AxiosError: `.message` is the generic HTTP-status
    // text a plain-Error-carrying-the-final-text fixture would let through
    // even if the component read the raw caught error instead of running it
    // through formatApiError.
    vi.mocked(environmentGroupService.transitionGroup).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 400',
      response: {
        status: 400,
        data: {
          detail:
            "The group cannot move to 'approved' because its members are not all able to: " +
            "Checkout API (in 'submitted'): ok; Checkout DB (in 'draft'): not allowed from 'draft'",
        },
      },
    });

    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole('button', { name: 'Approve Group' }));

    const alert = await screen.findByText(/Checkout DB \(in 'draft'\)/);
    expect(alert.textContent).toContain('Checkout API');
    expect(alert.textContent).toContain('Checkout DB');
    expect(alert.textContent).not.toContain('Request failed with status code');
  });

  it('refetches allowed transitions when the members states change, even though requestId/groupId stay the same', async () => {
    // Reproduces the stale-buttons defect: a successful group transition
    // changes the members' statuses via a new `bookings` prop from the
    // parent, but never `requestId`/`groupId`. An effect keyed on only
    // those two would never rerun, and "Approve Group" would keep
    // rendering after the group had already moved to `approved`.
    const { rerender } = render(
      <MemoryRouter>
        <GroupTransitionPanel
          requestId={REQUEST_ID}
          groupId={GROUP_ID}
          groupName={GROUP_NAME}
          bookings={[MEMBER_A, MEMBER_B]}
        />
      </MemoryRouter>
    );

    await screen.findByRole('button', { name: 'Approve Group' });
    expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(1);

    // Same ids, changed statuses — as if `onTransitioned` had just refreshed
    // the parent's data after a successful move to `approved`.
    const MEMBER_A_APPROVED: EnvBookingSummary = { ...MEMBER_A, status: 'approved' };
    const MEMBER_B_APPROVED: EnvBookingSummary = { ...MEMBER_B, status: 'approved' };
    vi.mocked(environmentGroupService.groupAllowedTransitions).mockResolvedValue([
      { from_state: 'approved', to_state: 'closed', label: 'Close Group' },
    ]);

    rerender(
      <MemoryRouter>
        <GroupTransitionPanel
          requestId={REQUEST_ID}
          groupId={GROUP_ID}
          groupName={GROUP_NAME}
          bookings={[MEMBER_A_APPROVED, MEMBER_B_APPROVED]}
        />
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(2)
    );
    expect(await screen.findByRole('button', { name: 'Close Group' })).toBeInTheDocument();
  });

  it('does not refetch on an unrelated re-render where the members statuses are unchanged', async () => {
    // Guards the fix itself: keying the effect on a freshly-built array (or
    // on `bookings` by identity) would refetch on every render, which would
    // make the test above pass for the wrong reason — the component simply
    // always fetching, discriminating nothing.
    const { rerender } = render(
      <MemoryRouter>
        <GroupTransitionPanel
          requestId={REQUEST_ID}
          groupId={GROUP_ID}
          groupName={GROUP_NAME}
          bookings={[MEMBER_A, MEMBER_B]}
        />
      </MemoryRouter>
    );

    await screen.findByRole('button', { name: 'Approve Group' });
    expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(1);

    // New array references, same ids and statuses as before.
    rerender(
      <MemoryRouter>
        <GroupTransitionPanel
          requestId={REQUEST_ID}
          groupId={GROUP_ID}
          groupName={GROUP_NAME}
          bookings={[{ ...MEMBER_A }, { ...MEMBER_B }]}
        />
      </MemoryRouter>
    );

    // Give any wrongful refetch a chance to happen before asserting it didn't.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(environmentGroupService.groupAllowedTransitions).toHaveBeenCalledTimes(1);
  });

  it('renders a load error instead of an eternal skeleton when the group allowed-transitions fetch fails', async () => {
    vi.mocked(environmentGroupService.groupAllowedTransitions).mockReset().mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Group not found' } },
    });

    renderPanel();

    expect(await screen.findByText('Group not found')).toBeInTheDocument();
    // Members still render even though the transition-set fetch failed.
    expect(screen.getByText('Checkout API')).toBeInTheDocument();
  });

  // --- Finding 1 regression: the repair path must be reachable from here ---

  it('gives each member its own transition control and its own link to the sibling, even when the group control set is empty (Finding 1)', async () => {
    // The group is out of step and the group's own intersection is empty —
    // exactly the state the out-of-step banner describes as needing repair.
    // Before the fix, this left the page with a diagnosis and no way to act
    // on it: no per-member control, no link to the sibling that needs fixing.
    vi.mocked(environmentGroupService.groupAllowedTransitions).mockReset().mockResolvedValue([]);
    vi.mocked(bookingService.getAllowedTransitions)
      .mockReset()
      .mockResolvedValue([{ from_state: 'submitted', to_state: 'approved', label: 'Approve' }]);

    renderPanel({ bookings: [MEMBER_A, MEMBER_B_DRAFT] });

    await screen.findByText(/out of step/);

    // A per-member control renders, driven by the individual endpoint, even
    // though the group's own intersection has nothing to offer.
    expect(await screen.findAllByRole('button', { name: 'Approve' })).toHaveLength(2);

    // A sibling is reachable from either member's row — this is what lets
    // someone fix "the other one" without hunting for it elsewhere.
    const linkToA = screen.getByRole('link', { name: 'Checkout API' });
    expect(linkToA).toHaveAttribute('href', `/bookings/${MEMBER_A.id}`);
    const linkToB = screen.getByRole('link', { name: 'Checkout DB' });
    expect(linkToB).toHaveAttribute('href', `/bookings/${MEMBER_B_DRAFT.id}`);
  });

  it("calls onMemberTransition with the member's own id when its individual control is clicked", async () => {
    vi.mocked(bookingService.getAllowedTransitions)
      .mockReset()
      .mockResolvedValue([{ from_state: 'submitted', to_state: 'approved', label: 'Approve' }]);
    const onMemberTransition = vi.fn().mockResolvedValue(undefined);

    const user = userEvent.setup();
    renderPanel({ onMemberTransition });

    const buttons = await screen.findAllByRole('button', { name: 'Approve' });
    expect(buttons).toHaveLength(2);
    await user.click(buttons[1]);

    expect(onMemberTransition).toHaveBeenCalledWith(MEMBER_B.id, 'approved', 'Approve');
  });
});
