import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface User {
  id: number;
  username: string;
  email: string;
  role: string;
  tenant_id: number;
  is_master_admin: boolean;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  // False while we still have a token but haven't loaded the user yet (page reload).
  // Route guards must wait for this before evaluating role checks.
  authInitialized: boolean;
  impersonationMode: boolean;
  impersonatingTenant: { id: number; name: string; slug: string } | null;
  originalToken: string | null;
}

const initialState: AuthState = {
  user: null,
  token: localStorage.getItem('token'),
  isAuthenticated: !!localStorage.getItem('token'),
  // With no token there's nothing to load → already resolved; with a token we must fetch the user.
  authInitialized: !localStorage.getItem('token'),
  impersonationMode: false,
  impersonatingTenant: null,
  originalToken: null,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials: (
      state,
      action: PayloadAction<{ user: User; token: string; refreshToken?: string }>
    ) => {
      state.user = action.payload.user;
      state.token = action.payload.token;
      state.isAuthenticated = true;
      state.authInitialized = true;
      localStorage.setItem('token', action.payload.token);
      // Optional because the reload path re-hydrates from an existing token and
      // has no new refresh token to store.
      if (action.payload.refreshToken) {
        localStorage.setItem('refresh_token', action.payload.refreshToken);
      }
    },
    // Mark auth resolution complete without changing credentials — used when the
    // reload user-fetch finishes (success handled by setCredentials; this covers
    // the "no user came back but keep going" edge).
    authResolved: (state) => {
      state.authInitialized = true;
    },
    logout: (state) => {
      state.user = null;
      state.token = null;
      state.isAuthenticated = false;
      state.authInitialized = true;
      state.impersonationMode = false;
      state.impersonatingTenant = null;
      state.originalToken = null;
      localStorage.removeItem('token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('impersonation_token');
    },
    enterImpersonation(
      state,
      action: PayloadAction<{ token: string; tenant: { id: number; name: string; slug: string } }>
    ) {
      state.originalToken = state.token;
      state.token = action.payload.token;
      state.impersonationMode = true;
      state.impersonatingTenant = action.payload.tenant;
      localStorage.setItem('impersonation_token', action.payload.token);
    },
    exitImpersonation(state) {
      if (state.originalToken) {
        localStorage.setItem('token', state.originalToken);
      }
      state.token = state.originalToken;
      state.impersonationMode = false;
      state.impersonatingTenant = null;
      state.originalToken = null;
      localStorage.removeItem('impersonation_token');
    },
  },
});

export const { setCredentials, authResolved, logout, enterImpersonation, exitImpersonation } =
  authSlice.actions;
export default authSlice.reducer;
