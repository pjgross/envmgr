import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AgreementGapIndicator from '../AgreementGapIndicator';

// The server's own wording, verbatim — agreement_gap_service names the project
// and the environment (`f"{project_name} has no usage agreement for
// {environment_name}"`). Nothing here composes a message of its own, so nothing
// here can render `#12` or `env #3`.
const GAP = 'Mortgage has no usage agreement for UAT-1';

describe('AgreementGapIndicator', () => {
  it('renders nothing at all for a booking with no gap', () => {
    const { container } = render(<AgreementGapIndicator gap={null} hasUnacknowledgedGap={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the server's message for an unacknowledged gap", async () => {
    render(<AgreementGapIndicator gap={GAP} hasUnacknowledgedGap />);

    const icon = screen.getByLabelText('Usage agreement gap');
    await userEvent.hover(icon);

    expect(await screen.findByText(GAP)).toBeInTheDocument();
  });

  // ACKNOWLEDGING IS NOT RESOLVING. The gap is computed from usage_agreement on
  // every read and is cleared only by recording the missing agreement, so an
  // acknowledged booking is still in gap and `?agreement_gap=true` still returns
  // it. An indicator that vanished on acknowledgement would leave that filter
  // showing rows with an empty cell — the "information lost, not merely hidden"
  // shape docs/pagination.md records.
  it('still marks an acknowledged gap, and says it was acknowledged', async () => {
    render(<AgreementGapIndicator gap={GAP} hasUnacknowledgedGap={false} />);

    const icon = screen.getByLabelText('Usage agreement gap, acknowledged');
    await userEvent.hover(icon);

    expect(await screen.findByText(`Acknowledged — ${GAP}`)).toBeInTheDocument();
  });

  // Colour is the only difference a sighted user sees between the two states at
  // a glance, so the two must not be colour-only: the accessible name differs
  // too. Asserting the names are distinct pins that, whatever the colours are.
  it('distinguishes acknowledged from unacknowledged by name, not by colour alone', () => {
    const { unmount } = render(<AgreementGapIndicator gap={GAP} hasUnacknowledgedGap />);
    const unacknowledged = screen.getByLabelText('Usage agreement gap').getAttribute('aria-label');
    unmount();

    render(<AgreementGapIndicator gap={GAP} hasUnacknowledgedGap={false} />);
    const acknowledged = screen
      .getByLabelText('Usage agreement gap, acknowledged')
      .getAttribute('aria-label');

    expect(unacknowledged).not.toBe(acknowledged);
  });

  // The by-name rule is kept BACKEND-side: agreement_gap_service composes the
  // message and names the project and the environment. What this component can
  // still get wrong is decorating it — appending an id, a booking number, a
  // "(env 3)". So the guarantee worth pinning here is PASS-THROUGH: the tooltip
  // is the server's string and nothing else.
  //
  // The obvious version of this test — render the fixture, assert no `/#\d/`
  // appears — asserts nothing about the component at all: the fixture contains
  // no digits, so only editing the test can make it fail. A review caught that.
  it("renders the server's message verbatim, decorating it with nothing", async () => {
    const gap = 'Mortgage has no usage agreement for UAT-1';
    render(<AgreementGapIndicator gap={gap} hasUnacknowledgedGap />);
    await userEvent.hover(screen.getByLabelText('Usage agreement gap'));

    const tooltip = await screen.findByRole('tooltip');
    expect(tooltip.textContent).toBe(gap);
  });
});
