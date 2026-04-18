import axios from 'axios';

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

// Handle auth errors — only redirect when a stored session expires,
// not when unauthenticated requests fail (e.g. login with wrong credentials)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && localStorage.getItem('token')) {
      localStorage.removeItem('token');
      localStorage.removeItem('impersonation_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;
