import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { store } from '../../../store';
import ReleaseList, { apiProjectId } from '../ReleaseList';

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
    listSystems: vi.fn().mockResolvedValue({ rows: [{ id: 7, name: 'Payments' }], total: 1 }),
  },
}));

vi.mock('../../../services/projectService', () => ({
  projectService: {
    listProjects: vi
      .fn()
      .mockResolvedValue({ rows: [{ id: 3, name: 'Mortgage' }], total: 1 }),
  },
}));

import { releaseService } from '../../../services/releaseService';
import { projectService } from '../../../services/projectService';

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

  it('dispatches the list fetch with the selected project id and a reset offset', async () => {
    renderPage('/releases?page=2');

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    const option = await screen.findByRole('option', { name: 'Mortgage' });
    await userEvent.click(option);

    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project_id: 3, offset: 0 })
      )
    );
  });

  it('sends no project_id at all once "All projects" is re-selected, not the string "any"', async () => {
    renderPage('/releases?page=2');
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    await userEvent.click(await screen.findByRole('option', { name: 'Mortgage' }));
    await waitFor(() =>
      expect(releaseService.list).toHaveBeenLastCalledWith(
        expect.objectContaining({ project_id: 3 })
      )
    );
    vi.mocked(releaseService.list).mockClear();

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    await userEvent.click(await screen.findByRole('option', { name: 'All projects' }));

    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());
    const params = vi.mocked(releaseService.list).mock.calls[0][0] as Record<string, unknown>;
    expect(params.project_id).toBeUndefined();
  });

  // Finding 4: fetching every project rather than only active ones would
  // offer archived projects as filter choices. Nothing else in this suite
  // inspects the call params, so dropping `is_active: true` here previously
  // left every test green.
  it('fetches only active projects for the Project filter (drops is_active: true otherwise)', async () => {
    renderPage();
    await waitFor(() =>
      expect(projectService.listProjects).toHaveBeenCalledWith(
        expect.objectContaining({ is_active: true })
      )
    );
  });

  // Finding 2: a bookmarked/shared link, or a colleague's project archived
  // out from under an open tab, leaves `project_id` in the URL pointing at a
  // project no longer in the active list. The grid stays filtered to it (see
  // apiProjectId below) but the old code rendered no matching MenuItem, so
  // the select showed blank — and, combined with `disabled={projects.length
  // === 0}`, was sometimes impossible to clear without hand-editing the URL.
  // The comment this replaced asserted that could never happen; it was wrong.
  it('keeps a project_id filter not in the active list visible and clearable', async () => {
    renderPage('/releases?project_id=9');
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());

    const combobox = await screen.findByRole('combobox', { name: 'Project' });
    expect(combobox).toHaveTextContent('Project #9 (unavailable)');
    expect(combobox).not.toHaveAttribute('aria-disabled', 'true');

    await userEvent.click(combobox);
    await userEvent.click(await screen.findByRole('option', { name: 'All projects' }));

    await waitFor(() => {
      const calls = vi.mocked(releaseService.list).mock.calls;
      const params = calls[calls.length - 1]?.[0] as Record<string, unknown>;
      expect(params.project_id).toBeUndefined();
    });
  });

  it('does not disable the Project select when the active list is empty but a filter is set', async () => {
    // Every project archived, or the picker fetch failed — either way
    // `projects` comes back empty while the URL still names one.
    vi.mocked(projectService.listProjects).mockResolvedValueOnce({ rows: [], total: 0 });
    renderPage('/releases?project_id=9');
    await waitFor(() => expect(projectService.listProjects).toHaveBeenCalled());

    const combobox = await screen.findByRole('combobox', { name: 'Project' });
    expect(combobox).not.toHaveAttribute('aria-disabled', 'true');
  });

  it('spells the project filter\'s "no selection" state `any`, never `all` (buildParams sentinel collision)', async () => {
    // `all` is buildParams' own "no selection" sentinel and is dropped
    // before a request is built. If this option were spelled `all`, the
    // URL would never distinguish it from the raw default at all — see
    // ScopeWindowsTable's identical apiScopeWindow.
    renderPage();
    await waitFor(() => expect(releaseService.list).toHaveBeenCalled());

    await userEvent.click(screen.getByRole('combobox', { name: 'Project' }));
    const allOption = await screen.findByRole('option', { name: 'All projects' });
    expect(allOption).toHaveAttribute('data-value', 'any');
  });
});

describe('apiProjectId', () => {
  it('treats "any" as no filter, not a value to send to the server', () => {
    expect(apiProjectId('any')).toBeUndefined();
  });

  it('treats an absent filter as no filter', () => {
    expect(apiProjectId(undefined)).toBeUndefined();
  });

  it('passes a chosen project id through as a number', () => {
    expect(apiProjectId('7')).toBe(7);
    expect(apiProjectId(7)).toBe(7);
  });
});
