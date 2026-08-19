import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ContentionMarker } from '../ContentionMarker';
import type { ContentionState } from '../../../types/contentionForecast';

// ONE MARKER COMPONENT, USED BY BOTH THE CALENDAR (Task 7) AND THE LIST
// (Task 6). B5 shipped three independent copies of a state->label map and
// nothing caught a future edit to one and not the others — this test exists
// so the label wording lives in exactly one place.
describe('ContentionMarker', () => {
  it('renders a distinct label for each of the three states', () => {
    const cases: [ContentionState, RegExp][] = [
      ['unowned', /needs escalating/i],
      ['owned', /awaiting a decision/i],
      ['decided', /decided/i],
    ];
    for (const [state, label] of cases) {
      const { unmount } = render(<ContentionMarker state={state} />);
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it('gives each state a label distinguishable from the other two', () => {
    // Deleting the per-state label and always rendering "Contention" would
    // still pass a test that only checked "some text is present" — this
    // asserts the three renders produce three DIFFERENT strings.
    const labels = (['unowned', 'owned', 'decided'] as const).map((state) => {
      const { container, unmount } = render(<ContentionMarker state={state} />);
      const text = container.textContent ?? '';
      unmount();
      return text;
    });
    expect(new Set(labels).size).toBe(3);
  });

  it('does not rely on colour alone', () => {
    // This repo has a completed a11y audit and colour-only state encoding is
    // exactly what it flags. Every state must carry text or an aria-label —
    // `{ hidden: true }` is required here because the marker icon is
    // aria-hidden (decorative; the adjacent text is the real accessible
    // name), which testing-library excludes from getByRole by default.
    render(<ContentionMarker state="owned" />);
    expect(screen.getByRole('img', { hidden: true })).toHaveAttribute('aria-label');
  });

  it('gives the icon a state-specific aria-label, not a generic one', () => {
    // A marker whose icon aria-label is always "Contention" would pass the
    // "has an aria-label" test above while telling a screen-reader user
    // nothing different across states.
    const { unmount: u1, container: c1 } = render(<ContentionMarker state="unowned" />);
    const unownedLabel = c1.querySelector('[role="img"]')?.getAttribute('aria-label');
    u1();
    const { unmount: u2, container: c2 } = render(<ContentionMarker state="decided" />);
    const decidedLabel = c2.querySelector('[role="img"]')?.getAttribute('aria-label');
    u2();
    expect(unownedLabel).toBeTruthy();
    expect(decidedLabel).toBeTruthy();
    expect(unownedLabel).not.toEqual(decidedLabel);
  });
});
