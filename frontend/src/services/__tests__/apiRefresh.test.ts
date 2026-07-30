import axios from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The interceptor calls bare axios.post for the refresh itself (going through the
// `api` instance would re-enter the interceptor), so that is what gets stubbed.
vi.mock('axios', async () => {
  const actual = await vi.importActual<typeof import('axios')>('axios');
  return { ...actual, default: { ...actual.default, post: vi.fn() } };
});

const originalLocation = window.location;

beforeEach(() => {
  localStorage.clear();
  vi.mocked(axios.post).mockReset();
  // window.location.href assignment would try to navigate under jsdom.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, href: '' },
  });
});

afterEach(() => {
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: originalLocation,
  });
  vi.resetModules();
});

/** Fresh module per test: the interceptor keeps in-flight refresh state. */
async function loadApi() {
  vi.resetModules();
  return (await import('../api')).default;
}

describe('access token refresh', () => {
  it('refreshes once and replays the original request', async () => {
    localStorage.setItem('token', 'expired-access');
    localStorage.setItem('refresh_token', 'valid-refresh');
    vi.mocked(axios.post).mockResolvedValue({
      data: { access_token: 'new-access', refresh_token: 'new-refresh' },
    });

    const api = await loadApi();
    let calls = 0;
    api.defaults.adapter = async (config) => {
      calls += 1;
      if (calls === 1) {
        return Promise.reject(
          Object.assign(new Error('401'), { config, response: { status: 401 } })
        );
      }
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    const response = await api.get('/environments');

    expect(response.data).toEqual({ ok: true });
    expect(axios.post).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('token')).toBe('new-access');
    // Rotation: the new refresh token must replace the spent one.
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh');
  });

  it('shares one refresh across concurrent 401s', async () => {
    // Every refresh rotates the token, so six parallel refreshes would present
    // five already-spent tokens — which the server treats as theft and answers by
    // revoking the whole family, silently signing the user out.
    localStorage.setItem('token', 'expired-access');
    localStorage.setItem('refresh_token', 'valid-refresh');
    vi.mocked(axios.post).mockImplementation(
      () =>
        new Promise((resolve) =>
          setTimeout(
            () => resolve({ data: { access_token: 'new-access', refresh_token: 'new-refresh' } }),
            5
          )
        ) as never
    );

    const api = await loadApi();
    const seen = new Set<string>();
    api.defaults.adapter = async (config) => {
      const key = `${config.url}:${config.headers?.Authorization}`;
      if (!seen.has(key) && config.headers?.Authorization === 'Bearer expired-access') {
        seen.add(key);
        return Promise.reject(
          Object.assign(new Error('401'), { config, response: { status: 401 } })
        );
      }
      return { data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config };
    };

    await Promise.all([
      api.get('/environments'),
      api.get('/bookings'),
      api.get('/releases'),
      api.get('/systems'),
    ]);

    expect(axios.post).toHaveBeenCalledTimes(1);
  });

  it('ends the session when the refresh itself fails', async () => {
    localStorage.setItem('token', 'expired-access');
    localStorage.setItem('refresh_token', 'dead-refresh');
    vi.mocked(axios.post).mockRejectedValue(new Error('401'));

    const api = await loadApi();
    api.defaults.adapter = async (config) =>
      Promise.reject(Object.assign(new Error('401'), { config, response: { status: 401 } }));

    await expect(api.get('/environments')).rejects.toBeTruthy();

    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(window.location.href).toBe('/login');
  });

  it('does not retry a request more than once', async () => {
    localStorage.setItem('token', 'expired-access');
    localStorage.setItem('refresh_token', 'valid-refresh');
    vi.mocked(axios.post).mockResolvedValue({
      data: { access_token: 'still-rejected', refresh_token: 'new-refresh' },
    });

    const api = await loadApi();
    let calls = 0;
    api.defaults.adapter = async (config) => {
      calls += 1;
      return Promise.reject(
        Object.assign(new Error('401'), { config, response: { status: 401 } })
      );
    };

    await expect(api.get('/environments')).rejects.toBeTruthy();
    // Original + one replay, then give up rather than loop.
    expect(calls).toBe(2);
  });

  it('does not refresh while impersonating', async () => {
    // The impersonation token has no refresh flow; refreshing would drop the
    // operator back into their own tenant mid-task without telling them.
    localStorage.setItem('token', 'own-access');
    localStorage.setItem('refresh_token', 'valid-refresh');
    localStorage.setItem('impersonation_token', 'imp-access');

    const api = await loadApi();
    api.defaults.adapter = async (config) =>
      Promise.reject(Object.assign(new Error('401'), { config, response: { status: 401 } }));

    await expect(api.get('/environments')).rejects.toBeTruthy();
    expect(axios.post).not.toHaveBeenCalled();
  });

  it('does not bounce an unauthenticated visitor off the login form', async () => {
    // No stored token: a wrong password must surface as an error on the form.
    const api = await loadApi();
    api.defaults.adapter = async (config) =>
      Promise.reject(Object.assign(new Error('401'), { config, response: { status: 401 } }));

    await expect(api.post('/auth/login', {})).rejects.toBeTruthy();
    expect(window.location.href).toBe('');
  });
});
