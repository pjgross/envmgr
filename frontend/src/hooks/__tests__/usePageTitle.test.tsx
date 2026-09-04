import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { usePageTitle } from '../usePageTitle';

function Probe({ override }: { override?: string }) {
  usePageTitle(override);
  return null;
}

const renderAt = (path: string, override?: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/environments" element={<Probe override={override} />} />
        <Route path="/environments/:id" element={<Probe override={override} />} />
      </Routes>
    </MemoryRouter>,
  );

describe('usePageTitle', () => {
  it('an override REPLACES the innermost crumb rather than being prepended to it', () => {
    // /environments/2's generic trail is "Environment, Environments" (innermost
    // first once reversed). The entity's real name must take the generic
    // "Environment" label's place, not sit in front of a trail that still
    // names it — a title reading "Mortgage_SIT, Environment, Environments"
    // would say the same page twice.
    renderAt('/environments/2', 'Mortgage_SIT');
    expect(document.title).toBe('Mortgage_SIT · Environments · EnvManager');
  });

  it('uses the generic trail with no leading separator when there is no override', () => {
    renderAt('/environments');
    expect(document.title).toBe('Environments · EnvManager');
    expect(document.title.startsWith('·')).toBe(false);
  });
});
