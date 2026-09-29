import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { Provider } from 'react-redux';
import { store } from '../../../store';
import ReleaseDetail from '../ReleaseDetail';

// The real singleton store (see environmentDetailComponentsDeepLink.test.tsx
// for the sibling precedent), not a hand-assembled reducer map: ReleaseDetail's
// default "Main" panel and the RAID panel each reach several slices deep
// (auth, customField, raid, tenantAdmin, …) via nested components, and a
// duplicated copy of store/index.ts's reducer object would silently drift
// from the real app shape the moment a slice is added there and not here.
// Only `releaseService.get` is mocked, so `fetchRelease` runs for real
// through the real reducer and produces `release.detail` the same way the
// app does. Every OTHER thunk these nested tabs dispatch on mount
// (fetchDependencyAlerts, fetchRaidItems, fetchUsers, …) is left real too —
// their services hit relative URLs with no server behind them in this test,
// which reject asynchronously and are absorbed by each thunk's own
// rejected-action handling, the same way ReadinessBanner's direct axios call
// degrades to "nothing to show" rather than throwing.
vi.mock('../../../services/releaseService', async () => {
  const actual = await vi.importActual<typeof import('../../../services/releaseService')>(
    '../../../services/releaseService',
  );
  return { ...actual, releaseService: { ...actual.releaseService, get: vi.fn() } };
});

import { releaseService } from '../../../services/releaseService';

const RELEASE = {
  id: 7,
  tenant_id: 1,
  name: 'R1',
  description: null,
  release_type: 'standard',
  release_kind: 'project' as const,
  owning_project_id: null,
  owning_project_name: null,
  parent_release_id: null,
  template_id: null,
  lifecycle_template_id: 1,
  status: 'draft',
  target_date: null,
  actual_date: null,
  scope_deadline: null,
  custom_fields: null,
  raised_by: 1,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  operations_group_id: null,
  operations_group_name: null,
  declared_stable_at: null,
  declared_stable_by_username: null,
  handover_confirmed_at: null,
  handover_confirmed_by_username: null,
};

// Full URL, not just the rendered tab: a `useState` fallback would also leave
// the clicked tab `aria-selected`, since MUI's own state still updates — only
// the URL tells "the tab changed" apart from "the tab is also in the URL".
function Path() {
  const location = useLocation();
  return <div data-testid="path">{location.pathname + location.search}</div>;
}

const renderAt = (search: string) =>
  render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[`/releases/7${search}`]}>
        <Routes>
          <Route path="/releases/:id" element={<><ReleaseDetail /><Path /></>} />
        </Routes>
      </MemoryRouter>
    </Provider>,
  );

describe('ReleaseDetail — the tab is in the URL', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(releaseService.get).mockResolvedValue(RELEASE);
  });

  it('opens the tab named by ?tab=', async () => {
    renderAt('?tab=rollback');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Rollback' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when no tab is named', async () => {
    renderAt('');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('opens Main when ?tab= names a tab that no longer exists', async () => {
    renderAt('?tab=gone');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Main' })).toHaveAttribute('aria-selected', 'true'),
    );
  });

  it('puts the tab in the URL when one is clicked', async () => {
    renderAt('');
    await userEvent.click(await screen.findByRole('tab', { name: 'RAID' }));
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'RAID' })).toHaveAttribute('aria-selected', 'true'),
    );
    expect(screen.getByTestId('path')).toHaveTextContent('/releases/7?tab=raid');
  });

  it('selects the Closeout tab from ?tab=closeout', async () => {
    renderAt('?tab=closeout');
    expect(await screen.findByRole('tab', { name: 'Closeout' })).toHaveAttribute('aria-selected', 'true');
  });
});

// UI-2: fourteen tabs overflow the strip, and MUI's scrollable Tabs does not
// bring an initially-selected tab into view — landing on ?tab=runbook from My
// work left the active tab off-screen. jsdom performs no layout, so this pins
// the STRUCTURE (the selected tab is asked to scroll into view), not a pixel.
describe('ReleaseDetail — the selected tab is scrolled into view', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(releaseService.get).mockResolvedValue(RELEASE);
  });

  // jsdom performs no layout and has no ResizeObserver, so both are stubbed.
  // The geometry is the one measured in Chrome (2026-09-29): the strip first
  // renders without MUI's arrow buttons and is scrolled correctly for that
  // width; MUI's IntersectionObserver then adds two 40px arrow buttons, the
  // scroller narrows by 80px and the selected tab ends up clipped. The fix
  // must re-reveal on that resize, and must do it by scrolling the STRIP —
  // never the page (scrollIntoView's `block` can move the page vertically).
  type Rect = { left: number; right: number };
  function stubGeometry(scroller: HTMLElement, rects: Map<Element, Rect>) {
    let scrollLeft = 0;
    Object.defineProperty(scroller, 'scrollLeft', {
      configurable: true,
      get: () => scrollLeft,
      set: (v: number) => { scrollLeft = v; },
    });
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const r = rects.get(this) ?? { left: 0, right: 0 };
      return { ...r, top: 0, bottom: 0, width: r.right - r.left, height: 0, x: r.left, y: 0, toJSON: () => r } as DOMRect;
    });
    return { get scrollLeft() { return scrollLeft; }, set scrollLeft(v: number) { scrollLeft = v; } };
  }

  it('reveals the selected tab again when the strip narrows after landing (arrow buttons appear)', async () => {
    const observed = new Map<Element, () => void>();
    const OriginalRO = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      constructor(private cb: () => void) {}
      observe(el: Element) { observed.set(el, this.cb); }
      unobserve(el: Element) { observed.delete(el); }
      disconnect() { for (const [el, cb] of observed) if (cb === this.cb) observed.delete(el); }
    };
    const pageScroll = vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
    try {
      renderAt('?tab=runbook');
      const runbook = await screen.findByRole('tab', { name: 'Runbook' });
      const scroller = runbook.closest('.MuiTabs-scroller') as HTMLElement;
      const rects = new Map<Element, Rect>();
      const geo = stubGeometry(scroller, rects);
      // Before the arrows: 1192px of strip, already scrolled to 292 — tab visible.
      geo.scrollLeft = 292;
      rects.set(scroller, { left: 280, right: 1472 });
      rects.set(runbook, { left: 1380, right: 1472 });
      // The arrows appear: the scroller narrows to 320–1432 and the tab is clipped.
      rects.set(scroller, { left: 320, right: 1432 });
      rects.set(runbook, { left: 1420, right: 1512 });
      await waitFor(() => expect(observed.has(scroller)).toBe(true));
      observed.get(scroller)!();
      expect(geo.scrollLeft).toBe(372);
      expect(pageScroll).not.toHaveBeenCalled();
    } finally {
      (globalThis as { ResizeObserver?: unknown }).ResizeObserver = OriginalRO;
      vi.restoreAllMocks();
    }
  });

  // MUI's own scrollSelectedIntoView already covers a tab CHANGE (it passes on
  // the pre-fix code too); kept to prove the resize handling above does not
  // fight it. The discriminating test is the one above.
  it('scrolls the strip back when the selected tab sits left of the visible area', async () => {
    renderAt('?tab=runbook');
    const runbook = await screen.findByRole('tab', { name: 'Runbook' });
    const scroller = runbook.closest('.MuiTabs-scroller') as HTMLElement;
    const rects = new Map<Element, Rect>();
    const geo = stubGeometry(scroller, rects);
    try {
      geo.scrollLeft = 372;
      rects.set(scroller, { left: 320, right: 1432 });
      const main = screen.getByRole('tab', { name: 'Main' });
      rects.set(main, { left: 250, right: 330 });   // 70px out of view on the left
      await userEvent.click(main);
      await waitFor(() => expect(geo.scrollLeft).toBe(302));
    } finally {
      vi.restoreAllMocks();
    }
  });
});
