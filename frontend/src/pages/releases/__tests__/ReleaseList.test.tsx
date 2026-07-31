import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ReleaseList from '../ReleaseList';

// No HTTP — this test is about the wiring between the Status control and the
// dispatched fetch, not about what the server returns.
vi.mock('../../../services/releaseService', () => ({
  releaseService: {
    list: vi.fn().mockResolvedValue({ rows: [], total: 0 }),
    listBacklogChanges: vi.fn().mockResolvedValue([]),
  },
}));

vi.mock('../../../services/systemService', () => ({
  systemService: {
    listSystems: vi.fn().mockResolvedValue([{ id: 7, name: 'Payments' }]),
  },
}));

import { releaseService } from '../../../services/releaseService';

function renderPage(initialEntry = '/releases') {
  return render(
    <Provider store={store}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ReleaseList />
      </MemoryRouter>
    </Provider>
  );
}

// Regression coverage for the class of bug this whole conversion exists to
// fix: a filter control rebound to local component state (never reaching the
// server), or a `filterKeys` entry naming a parameter the server ignores.
// Neither the column-flag tests nor the slice arithmetic tests would catch
// that — the app would look like it filtered, right up until the page did
// not actually change.
describe('ReleaseList status filter wiring', () => {
  it('dispatches the list fetch with the selected status and a reset offset, not a carried-over page', async () => {
    // Start on page 2 (offset 50) so a failure to reset the page on filter
    // change is observable.
    renderPage('/releases?page=2');

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Status' }));
    const option = await screen.findByRole('option', { name: 'Draft' });
    await userEvent.click(option);

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'draft', offset: 0 })
      )
    );
  });

  // GAP 4: the Status control above was the only one of the four filter
  // controls (Status, Type, Kind, System) with any coverage. The other
  // three are just as prone to being rebound to local state (or to a
  // `filterKeys` entry the server ignores) without anything failing — the
  // grid would look filtered and simply not be. Each of these mirrors the
  // Status test's rigor: start on page 2 (offset 50) so a failure to reset
  // the page on filter change is observable too.
  it('dispatches the list fetch with the selected release type and a reset offset', async () => {
    renderPage('/releases?page=2');

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Type' }));
    const option = await screen.findByRole('option', { name: 'hotfix' });
    await userEvent.click(option);

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ release_type: 'hotfix', offset: 0 })
      )
    );
  });

  it('dispatches the list fetch with the selected system id and a reset offset', async () => {
    renderPage('/releases?page=2');

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'System' }));
    const option = await screen.findByRole('option', { name: 'Payments' });
    await userEvent.click(option);

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ system_id: '7', offset: 0 })
      )
    );
  });

  // The Kind control is a ToggleButtonGroup, not a select, so it needs a
  // click on the target toggle button rather than an open-then-pick-option
  // interaction.
  it('dispatches the list fetch with the selected release kind and a reset offset', async () => {
    renderPage('/releases?page=2');

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('button', { name: 'Enterprise' }));

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ release_kind: 'enterprise', offset: 0 })
      )
    );
  });
});
