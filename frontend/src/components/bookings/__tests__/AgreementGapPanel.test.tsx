/**
 * A3 Task 6 — the usage-agreement gap, as a user sees it on one booking.
 *
 * Two rules govern every assertion in this file:
 *
 *  - **A3 WARNS, IT NEVER BLOCKS.** Nothing here may prevent, disable or gate
 *    a booking. The panel is a message and one optional control.
 *  - **ACKNOWLEDGING IS NOT RESOLVING.** An acknowledged gap still shows the
 *    gap; it merely stops being unacknowledged. Adding the missing usage
 *    agreement clears it on its own — the gap is computed, never stored — so
 *    no copy here may imply the warning must be acknowledged to go away.
 *
 * The ack has no slice thunk (see agreementGapService), so the component's own
 * catch is the ONLY place the server's reason can be recovered. The failure
 * test below therefore rejects with an **AxiosError shape**: a test that
 * rejects with a plain `Error` carrying the final text passes while the app
 * shows "Request failed with status code 409".
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/agreementGapService', () => ({
  agreementGapService: { ackGap: vi.fn() },
}));

import { agreementGapService } from '../../../services/agreementGapService';
import AgreementGapPanel from '../AgreementGapPanel';

// Deliberately distinct from every other booking fixture in this suite
// (GroupTransitionPanel uses 75xx, bookingDetailRepairPath 96xx) so a
// wrong-data-source bug cannot pass by numeric coincidence.
const BOOKING_ID = 8801;
const OTHER_BOOKING_ID = 8802;
const USER_ID = 4401;

// The server's own wording, verbatim — agreement_gap_service names the project
// and the environment and never falls back to an id.
const GAP =
  "Mortgage Replatform's booking falls outside its agreed window for Staging (1 Jan 2026 – 30 Jun 2026)";
const OTHER_GAP = 'Mortgage Replatform has no usage agreement for Integration';

function renderPanel(overrides: Partial<React.ComponentProps<typeof AgreementGapPanel>> = {}) {
  const props: React.ComponentProps<typeof AgreementGapPanel> = {
    bookingId: BOOKING_ID,
    gap: GAP,
    hasUnacknowledgedGap: true,
    currentUserId: USER_ID,
    currentUsername: 'rmanager',
    ...overrides,
  };
  const utils = render(<AgreementGapPanel {...props} />);
  return {
    ...utils,
    rerenderWith: (next: Partial<React.ComponentProps<typeof AgreementGapPanel>>) =>
      utils.rerender(<AgreementGapPanel {...props} {...next} />),
  };
}

beforeEach(() => {
  vi.mocked(agreementGapService.ackGap).mockReset().mockResolvedValue({
    notes: null,
    acknowledged_by: USER_ID,
    acknowledged_at: '2026-08-08T10:30:00Z',
  });
});

describe('AgreementGapPanel — a booking with no gap', () => {
  it('renders nothing at all', () => {
    const { container } = renderPanel({ gap: null, hasUnacknowledgedGap: false });
    expect(container).toBeEmptyDOMElement();
  });
});

describe('AgreementGapPanel — an unacknowledged gap', () => {
  it('renders the gap message and an Acknowledge control', () => {
    renderPanel();
    expect(screen.getByText(GAP)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Acknowledge/i })).toBeInTheDocument();
  });

  it('says the booking is unaffected — the warning blocks nothing', () => {
    renderPanel();
    expect(screen.getByText(/warning only/i)).toBeInTheDocument();
  });

  it('says an agreement covering the booking clears it, without acknowledging', () => {
    renderPanel();
    expect(screen.getByText(/clears this warning/i)).toBeInTheDocument();
  });

  it('acknowledging sends the notes to the ack endpoint for this booking, then names who and when', async () => {
    const user = userEvent.setup();
    vi.mocked(agreementGapService.ackGap).mockResolvedValue({
      notes: 'Agreement extension already requested',
      acknowledged_by: USER_ID,
      acknowledged_at: '2026-08-08T10:30:00Z',
    });
    const onAcknowledged = vi.fn();
    renderPanel({ onAcknowledged });

    await user.type(
      screen.getByLabelText(/Notes \(optional\)/i),
      'Agreement extension already requested'
    );
    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    await waitFor(() =>
      expect(agreementGapService.ackGap).toHaveBeenCalledWith(
        BOOKING_ID,
        'Agreement extension already requested'
      )
    );
    // Who and when — by name, never a user id.
    const ackLine = await screen.findByText(/Acknowledged by rmanager/i);
    expect(ackLine).toBeInTheDocument();
    expect(ackLine.textContent).not.toContain(String(USER_ID));
    expect(ackLine.textContent).toMatch(/2026/);
    // The parent is told, so it can refetch the booking.
    await waitFor(() => expect(onAcknowledged).toHaveBeenCalledTimes(1));
  });

  it('still shows the gap after acknowledging — acknowledging is not resolving', async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    await screen.findByText(/Acknowledged by/i);
    expect(screen.getByText(GAP)).toBeInTheDocument();
  });
});

describe('AgreementGapPanel — an acknowledgement recorded against somebody else', () => {
  // The guard at `ackAuthor` exists so a name is printed only when the returned
  // `acknowledged_by` is the person looking. It cannot be reached through the
  // product today (`upsert_ack` always records the caller), which is exactly
  // why it needs a test: without one it is untested defensive code that a
  // reader would mistake for verified behaviour, and the alternative reading —
  // "name whoever is looking" — would attribute another user's decision to the
  // current one.
  it('reports when it was acknowledged but names nobody, rather than naming the wrong person', async () => {
    const user = userEvent.setup();
    const OTHER_USER_ID = 4402;
    vi.mocked(agreementGapService.ackGap).mockResolvedValue({
      notes: null,
      acknowledged_by: OTHER_USER_ID,
      acknowledged_at: '2026-08-08T10:30:00Z',
    });
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    const ackLine = await screen.findByTestId('agreement-gap-ack');
    expect(ackLine).toHaveTextContent(/^Acknowledged on /);
    expect(ackLine.textContent).not.toMatch(/rmanager/);
    // And no id leaks in place of the name.
    expect(ackLine.textContent).not.toContain(String(OTHER_USER_ID));
  });
});

describe('AgreementGapPanel — a failed acknowledgement', () => {
  it("renders the server's reason, not the raw HTTP status line", async () => {
    const user = userEvent.setup();
    // A real AxiosError shape: `.message` is the generic status text a naive
    // implementation would show instead of `response.data.detail`.
    vi.mocked(agreementGapService.ackGap).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Booking not found' } },
    });
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    expect(await screen.findByText('Booking not found')).toBeInTheDocument();
    expect(screen.queryByText(/Request failed with status code/)).not.toBeInTheDocument();
  });

  it('leaves the Acknowledge control usable — an error state, not a permanently busy button', async () => {
    const user = userEvent.setup();
    vi.mocked(agreementGapService.ackGap).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: { detail: 'Something went wrong' } },
    });
    renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));

    await screen.findByText('Something went wrong');
    await waitFor(() => expect(screen.getByRole('button', { name: /Acknowledge/i })).toBeEnabled());
    // And the gap is still there to be acted on — a failed ack resolves nothing.
    expect(screen.getByText(GAP)).toBeInTheDocument();
  });
});

describe('AgreementGapPanel — an already-acknowledged gap', () => {
  it('still shows the gap, and no longer offers the Acknowledge control', () => {
    renderPanel({ hasUnacknowledgedGap: false });
    expect(screen.getByText(GAP)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Acknowledge/i })).not.toBeInTheDocument();
    expect(screen.getByText(/has been acknowledged/i)).toBeInTheDocument();
  });
});

describe('AgreementGapPanel — re-rendered for a different booking', () => {
  // Only ever mounting hides stale state: two A2 defects needed a second
  // render to surface. The in-session acknowledgement belongs to ONE booking,
  // and BookingDetail re-renders this panel with new props whenever the
  // booking it displays changes.
  it('does not carry one booking’s acknowledgement over to the next', async () => {
    const user = userEvent.setup();
    const { rerenderWith } = renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));
    await screen.findByText(/Acknowledged by/i);

    rerenderWith({
      bookingId: OTHER_BOOKING_ID,
      gap: OTHER_GAP,
      hasUnacknowledgedGap: true,
    });

    await waitFor(() => expect(screen.queryByText(/Acknowledged by/i)).not.toBeInTheDocument());
    expect(screen.getByText(OTHER_GAP)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Acknowledge/i })).toBeInTheDocument();
  });

  it('clears a failed acknowledgement’s error when the booking changes', async () => {
    const user = userEvent.setup();
    vi.mocked(agreementGapService.ackGap).mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Booking not found' } },
    });
    const { rerenderWith } = renderPanel();

    await user.click(screen.getByRole('button', { name: /Acknowledge/i }));
    await screen.findByText('Booking not found');

    rerenderWith({ bookingId: OTHER_BOOKING_ID, gap: OTHER_GAP });

    await waitFor(() => expect(screen.queryByText('Booking not found')).not.toBeInTheDocument());
  });
});
