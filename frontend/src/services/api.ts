import axios from 'axios';
import type { AxiosError, InternalAxiosRequestConfig } from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add auth token to requests — impersonation token takes precedence
api.interceptors.request.use((config) => {
  const impersonationToken = localStorage.getItem('impersonation_token');
  const token = impersonationToken || localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Access tokens now last ~15 minutes, so a 401 mid-session is expected rather
// than exceptional: exchange the refresh token and replay the request once. Only
// when that exchange fails does the session actually end.
//
// Refreshes are shared through a single in-flight promise. Without that, a page
// that fires six requests at once on load would send six refreshes; since every
// refresh rotates the token, five of them would present an already-spent token
// and the server would treat that as theft and revoke the whole family.
let refreshInFlight: Promise<string> | null = null;

function endSession() {
  localStorage.removeItem('token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('impersonation_token');
  window.location.href = '/login';
}

async function refreshAccessToken(): Promise<string> {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) throw new Error('no refresh token');

  // A bare axios call, not `api`: going through the instance would re-enter this
  // interceptor if the refresh itself 401s.
  const { data } = await axios.post('/api/v1/auth/refresh', {
    refresh_token: refreshToken,
  });
  localStorage.setItem('token', data.access_token);
  localStorage.setItem('refresh_token', data.refresh_token);
  return data.access_token;
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const request = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;

    const isAuthFailure = error.response?.status === 401;
    const canRetry =
      isAuthFailure &&
      request &&
      !request._retried &&
      !request.url?.includes('/auth/refresh') &&
      !request.url?.includes('/auth/login') &&
      !!localStorage.getItem('refresh_token') &&
      // While impersonating, the active credential is the impersonation token,
      // which has no refresh flow — refreshing would silently drop the operator
      // back into their own tenant mid-task.
      !localStorage.getItem('impersonation_token');

    if (canRetry) {
      try {
        refreshInFlight = refreshInFlight ?? refreshAccessToken().finally(() => {
          refreshInFlight = null;
        });
        const token = await refreshInFlight;
        request._retried = true;
        request.headers.Authorization = `Bearer ${token}`;
        return api.request(request);
      } catch {
        endSession();
        return Promise.reject(error);
      }
    }

    // Unauthenticated requests failing (a wrong password on the login form) must
    // not bounce the visitor to /login — they are already there.
    if (isAuthFailure && localStorage.getItem('token')) {
      endSession();
    }
    return Promise.reject(error);
  }
);

export default api;
