import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ComputedColumnHeader from '../ComputedColumnHeader';

describe('ComputedColumnHeader', () => {
  it('renders the label', () => {
    render(<ComputedColumnHeader label="Phases" />);
    expect(screen.getByText('Phases')).toBeInTheDocument();
  });

  it('explains why the column cannot be sorted', async () => {
    render(<ComputedColumnHeader label="Phases" />);
    await userEvent.hover(screen.getByText('Phases'));
    expect(
      await screen.findByText(/not sortable across all results/i)
    ).toBeInTheDocument();
  });

  describe('keyboard reachability', () => {
    // jsdom (unlike real browsers) reports `:focus-visible` as never matching,
    // even for a genuine Tab-driven focus — see https://github.com/jsdom/jsdom
    // and MUI's own fallback in useIsFocusVisible.js. MUI's Tooltip tries
    // `target.matches(':focus-visible')` first and only falls back to its own
    // keyboard-modality heuristic if that throws (as it does in real browsers
    // that predate the pseudo-class). Making `matches` throw here forces MUI
    // down that fallback path, which is what actually decides "was this focus
    // keyboard-driven" in production — without this, the test would exercise
    // jsdom's stub answer instead of MUI's real logic, and the mutation check
    // (remove tabIndex) would fail to fail loudly enough to trust.
    let originalMatches: typeof Element.prototype.matches;

    beforeEach(() => {
      originalMatches = Element.prototype.matches;
      Element.prototype.matches = function (selector: string) {
        if (selector === ':focus-visible') {
          throw new DOMException('not supported', 'SyntaxError');
        }
        return originalMatches.call(this, selector);
      };
    });

    afterEach(() => {
      Element.prototype.matches = originalMatches;
    });

    it('reveals the explanation on Tab, with no mouse involved', async () => {
      render(<ComputedColumnHeader label="Phases" />);
      const label = screen.getByText('Phases');

      await userEvent.tab();

      expect(label).toHaveFocus();
      expect(
        await screen.findByText(/not sortable across all results/i)
      ).toBeInTheDocument();
    });
  });
});
