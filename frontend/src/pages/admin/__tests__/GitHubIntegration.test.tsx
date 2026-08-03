import { render, screen } from '@testing-library/react';
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
});
