import api from './api';

export interface LoginCredentials {
  username: string;
  password: string;
  tenant_slug: string;
}

export const authService = {
  login: async (credentials: LoginCredentials) => {
    const response = await api.post('/auth/login', credentials);
    return response.data;
  },

  /** Revoke this session server-side. Best-effort: the local state is cleared
   *  either way, so a failed call must not trap the user in a signed-in UI. */
  logout: async () => {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) return;
    try {
      await api.post('/auth/logout', { refresh_token: refreshToken });
    } catch {
      // Already expired or revoked — nothing left to end.
    }
  },

  getCurrentUser: async () => {
    const response = await api.get('/auth/me');
    return response.data;
  },
};
