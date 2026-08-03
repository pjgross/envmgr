import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/environmentComparisonService', () => ({
  environmentComparisonService: { compare: vi.fn() },
}));

vi.mock('../../../hooks/useAllEnvironments', () => ({
  useAllEnvironments: vi.fn(() => ({
    environments: [
      { id: 2, name: 'SIT' },
      { id: 3, name: 'UAT' },
    ],
    loading: false,
    truncated: false,
  })),
}));

import { environmentComparisonService } from '../../../services/environmentComparisonService';
import { useAllEnvironments } from '../../../hooks/useAllEnvironments';
import EnvironmentCompare from '../EnvironmentCompare';

const EMPTY = {
  left: { id: 2, name: 'SIT', status: 'active' },
  right: { id: 3, name: 'UAT', status: 'active' },
  systems: [],
  subsystems: [],
  summary: { compared: 0, differing: 0, by_kind: { presence: 0, mocked: 0, version: 0, host_shape: 0 } },
};

function renderPage(url = '/environments/compare?left=2&right=3') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <EnvironmentCompare />
    </MemoryRouter>
  );
}

describe('EnvironmentCompare', () => {
  // The mock's call history is otherwise shared across `it`s in this file
  // (module-level `vi.mock`, no global clearMocks) — without this, a later
  // "not called" assertion would fail on an earlier test's calls, not on
  // this page's behaviour.
  beforeEach(() => {
    vi.mocked(environmentComparisonService.compare).mockClear();
  });

  it('reads both environments from the URL and fetches that pair', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    await waitFor(() =>
      expect(environmentComparisonService.compare).toHaveBeenCalledWith(2, 3)
    );
  });

  it('does not fetch until both sides are chosen', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage('/environments/compare?left=2');
    // Give any effect a chance to run before asserting the negative.
    await new Promise((r) => setTimeout(r, 50));
    expect(environmentComparisonService.compare).not.toHaveBeenCalled();
  });

  it('says the environments match rather than showing an empty table', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    expect(await screen.findByText(/match on all four dimensions/i)).toBeInTheDocument();
  });

  it('swap exchanges the two sides', async () => {
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);
    renderPage();
    await waitFor(() => expect(environmentComparisonService.compare).toHaveBeenCalled());
    vi.mocked(environmentComparisonService.compare).mockClear();

    await userEvent.click(screen.getByRole('button', { name: /swap/i }));

    await waitFor(() =>
      expect(environmentComparisonService.compare).toHaveBeenCalledWith(3, 2)
    );
  });

  it('surfaces a truncated environment list, because a picker missing options is silent', async () => {
    vi.mocked(useAllEnvironments).mockReturnValueOnce({
      environments: [{ id: 2, name: 'SIT' }],
      loading: false,
      truncated: true,
    } as ReturnType<typeof useAllEnvironments>);
    vi.mocked(environmentComparisonService.compare).mockResolvedValue(EMPTY);

    renderPage('/environments/compare');

    expect(await screen.findByText(/only the first/i)).toBeInTheDocument();
  });
});
