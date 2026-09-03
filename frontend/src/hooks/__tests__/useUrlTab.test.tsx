import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { useUrlTab } from '../useUrlTab';

const KEYS = ['main', 'gates', 'raid'] as const;

function Probe() {
  const [tab, setTab] = useUrlTab(KEYS, 'main');
  const location = useLocation();
  return (
    <div>
      <span data-testid="tab">{tab}</span>
      <span data-testid="search">{location.search}</span>
      <button onClick={() => setTab('raid')}>go raid</button>
    </div>
  );
}

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/r/:id" element={<Probe />} />
      </Routes>
    </MemoryRouter>,
  );

describe('useUrlTab', () => {
  it('reads the tab from ?tab=', () => {
    renderAt('/r/7?tab=gates');
    expect(screen.getByTestId('tab')).toHaveTextContent('gates');
  });

  it('falls back to the default when ?tab= is absent', () => {
    renderAt('/r/7');
    expect(screen.getByTestId('tab')).toHaveTextContent('main');
  });

  it('falls back to the default when ?tab= is not a known key', () => {
    // A stale bookmark from before a tab was renamed must not render a blank
    // page — it lands on the default, exactly as if no tab had been named.
    renderAt('/r/7?tab=does-not-exist');
    expect(screen.getByTestId('tab')).toHaveTextContent('main');
  });

  it('writes the tab into the URL', async () => {
    renderAt('/r/7');
    await userEvent.click(screen.getByRole('button', { name: 'go raid' }));
    expect(screen.getByTestId('tab')).toHaveTextContent('raid');
    expect(screen.getByTestId('search')).toHaveTextContent('tab=raid');
  });

  it('preserves other query params when it changes the tab', () => {
    // A list filter, a selected row — switching tabs must not silently drop a
    // param another feature owns.
    renderAt('/r/7?tab=main&status=open');
    expect(screen.getByTestId('search')).toHaveTextContent('status=open');
  });

  it('two hooks with different param names do not overwrite each other', async () => {
    // EnterpriseTabs renders inside ReleaseDetail's `enterprise` tab, so both
    // are live on one URL. Without a distinct param they fight, and the inner
    // strip silently drives the outer one.
    render(
      <MemoryRouter initialEntries={['/r/7?tab=enterprise&etab=members']}>
        <Routes>
          <Route path="/r/:id" element={<TwoTabProbe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId('outer')).toHaveTextContent('enterprise');
    expect(screen.getByTestId('inner')).toHaveTextContent('members');
    await userEvent.click(screen.getByRole('button', { name: 'inner report' }));
    expect(screen.getByTestId('outer')).toHaveTextContent('enterprise');
    expect(screen.getByTestId('inner')).toHaveTextContent('report');
  });
});

function TwoTabProbe() {
  const [outer] = useUrlTab(['main', 'enterprise'], 'main');
  const [inner, setInner] = useUrlTab(['main', 'members', 'report'], 'main', 'etab');
  return (
    <div>
      <span data-testid="outer">{outer}</span>
      <span data-testid="inner">{inner}</span>
      <button onClick={() => setInner('report')}>inner report</button>
    </div>
  );
}
