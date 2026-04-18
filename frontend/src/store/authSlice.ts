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
  impersonationMode: boolean;
  impersonatingTenant: { id: number; name: string; slug: string } | null;
  originalToken: string | null;
}

const initialState: AuthState = {
  user: null,
  token: localStorage.getItem('token'),
  isAuthenticated: !!localStorage.getItem('token'),
  impersonationMode: false,
  impersonatingTenant: null,
  originalToken: null,
};

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    setCredentials: (state, action: PayloadAction<{ user: User; token: string }>) => {
      state.user = action.payload.user;
      state.token = action.payload.token;
      state.isAuthenticated = true;
      localStorage.setItem('token', action.payload.token);
    },
    logout: (state) => {
      state.user = null;
      state.token = null;
      state.isAuthenticated = false;
      state.impersonationMode = false;
      state.impersonatingTenant = null;
      state.originalToken = null;
      localStorage.removeItem('token');
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

export const { setCredentials, logout, enterImpersonation, exitImpersonation } = authSlice.actions;
export default authSlice.reducer;
