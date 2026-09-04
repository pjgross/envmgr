import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom';
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
      <button onClick={() => setTab('gates')}>go gates</button>
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

  it('preserves other query params when it changes the tab', async () => {
    // A list filter, a selected row — switching tabs must not silently drop a
    // param another feature owns.
    renderAt('/r/7?tab=main&status=open');
    expect(screen.getByTestId('search')).toHaveTextContent('status=open');
    // Actually change the tab and verify status=open survives the write
    await userEvent.click(screen.getByRole('button', { name: 'go raid' }));
    expect(screen.getByTestId('tab')).toHaveTextContent('raid');
    expect(screen.getByTestId('search')).toHaveTextContent('tab=raid');
    expect(screen.getByTestId('search')).toHaveTextContent('status=open');
  });

  it('two hooks with different param names do not overwrite each other', async () => {
    // A page with two nested tab strips live on one URL at once needs a
    // second param — `etab` here, illustratively — or the inner strip
    // silently drives the outer one. (No page in this app actually nests two
    // strips today; the capability still needs to hold if one ever does.)
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

  it('uses replace, not push, so Back exits the page', async () => {
    // Clicking through five tabs then pressing Back should leave the page, not
    // walk back through each tab. Without replace: true, pressing Back after
    // changing the tab would stay on the page with a previous tab param.
    // With replace: true, multiple tab changes don't create history entries.
    render(
      <MemoryRouter initialEntries={['/r/7', '/r/7?tab=main']}>
        <Routes>
          <Route path="/r/:id" element={<ProbeWithBack />} />
        </Routes>
      </MemoryRouter>,
    );

    // Should start on /r/7?tab=main
    expect(screen.getByTestId('tab')).toHaveTextContent('main');

    // Change tab from main to gates using replace (no history entry added)
    await userEvent.click(screen.getByRole('button', { name: 'go gates' }));
    expect(screen.getByTestId('tab')).toHaveTextContent('gates');

    // Change tab from gates to raid using replace (no history entry added)
    await userEvent.click(screen.getByRole('button', { name: 'go raid' }));
    expect(screen.getByTestId('tab')).toHaveTextContent('raid');

    // Navigate back once: with replace: true, the tab changes don't add history,
    // so back should go to the initial /r/7 entry (no tab param).
    // If push were used, back from raid would show gates instead.
    const backButton = screen.getByRole('button', { name: 'back' });
    await userEvent.click(backButton);

    // Back should return to the initial /r/7 (the first entry), which has no tab param
    // so it falls back to the default 'main'
    expect(screen.getByTestId('tab')).toHaveTextContent('main');
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

function ProbeWithBack() {
  const [tab, setTab] = useUrlTab(KEYS, 'main');
  const navigate = useNavigate();
  return (
    <div>
      <span data-testid="tab">{tab}</span>
      <button onClick={() => setTab('gates')}>go gates</button>
      <button onClick={() => setTab('raid')}>go raid</button>
      <button onClick={() => navigate(-1)}>back</button>
    </div>
  );
}
