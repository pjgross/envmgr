import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../../services/githubIntegrationService', () => ({
  githubIntegrationService: {
    status: vi.fn(),
    connect: vi.fn(),
    poll: vi.fn(),
    disconnect: vi.fn(),
  },
}));

import { githubIntegrationService } from '../../../services/githubIntegrationService';
import GitHubIntegration from '../GitHubIntegration';

function renderPage() {
  return render(
    <MemoryRouter>
      <GitHubIntegration />
    </MemoryRouter>
  );
}

describe('GitHubIntegration', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the user code and the verification link after starting', async () => {
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: false, github_login: null, connected_at: null,
    });
    vi.mocked(githubIntegrationService.connect).mockResolvedValue({
      handle: 'h1', user_code: 'WDJB-MJHT',
      verification_uri: 'https://github.com/login/device',
      expires_in: 900, interval: 5,
    });
    vi.mocked(githubIntegrationService.poll).mockResolvedValue({ status: 'pending' });

    renderPage();
    await userEvent.click(await screen.findByRole('button', { name: /connect github/i }));

    expect(await screen.findByText('WDJB-MJHT')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /github\.com\/login\/device/i })).toBeInTheDocument();
  });

  it('reports the connected account once polling succeeds', async () => {
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: true, github_login: 'octocat', connected_at: null,
    });

    renderPage();
    expect(await screen.findByText(/octocat/)).toBeInTheDocument();
  });

  it('says plainly that disconnecting does not revoke the grant at GitHub', async () => {
    // Telling someone their token is dead when it is not would be worse than
    // the extra sentence.
    vi.mocked(githubIntegrationService.status).mockResolvedValue({
      connected: true, github_login: 'octocat', connected_at: null,
    });

    renderPage();
    await screen.findByText(/octocat/);
    expect(screen.getByText(/still need to revoke it in GitHub/i)).toBeInTheDocument();
  });

  it('keeps GitHub\'s slow_down interval for later polls, not just the next one', async () => {
    // GitHub's device flow says an increased interval applies to ALL later
    // requests. Recomputing from the original each tick would quietly go back
    // to polling fast, which is how a client gets rate-limited.
    vi.useFakeTimers();
    try {
      vi.mocked(githubIntegrationService.status).mockResolvedValue({
        connected: false, github_login: null, connected_at: null,
      });
      vi.mocked(githubIntegrationService.connect).mockResolvedValue({
        handle: 'h1', user_code: 'WDJB-MJHT',
        verification_uri: 'https://github.com/login/device',
        expires_in: 900, interval: 1,
      });
      vi.mocked(githubIntegrationService.poll)
        .mockResolvedValueOnce({ status: 'slow_down', interval: 5 })
        .mockResolvedValue({ status: 'pending' });

      // `screen.findBy*`/`userEvent` both poll or wait via real timers, and
      // @testing-library/dom does not detect Vitest's fake timers (it only
      // recognises Jest's), so either hangs forever once `vi.useFakeTimers()`
      // is active. `vi.waitFor` is fake-timer-aware — it advances the faked
      // clock itself each iteration — so use it in place of `findBy*`, and
      // `fireEvent.click` in place of `userEvent.click` to dispatch the click
      // without going through user-event's own real-timer-dependent machinery.
      renderPage();
      await vi.waitFor(() =>
        expect(screen.getByRole('button', { name: /connect github/i })).toBeInTheDocument()
      );
      fireEvent.click(screen.getByRole('button', { name: /connect github/i }));
      await vi.waitFor(() => expect(screen.getByText('WDJB-MJHT')).toBeInTheDocument());

      // First poll after the original 1s.
      await vi.advanceTimersByTimeAsync(1_000);
      expect(githubIntegrationService.poll).toHaveBeenCalledTimes(1);

      // The backoff is now 5s: at 1s more, nothing further should have fired.
      await vi.advanceTimersByTimeAsync(1_000);
      expect(githubIntegrationService.poll).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(4_000);
      expect(githubIntegrationService.poll).toHaveBeenCalledTimes(2);

      // And it STAYS at 5s — the plain `pending` response carries no interval,
      // so a reset to the original would fire again after 1s.
      await vi.advanceTimersByTimeAsync(1_000);
      expect(githubIntegrationService.poll).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
