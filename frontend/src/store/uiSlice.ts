import { createSlice, PayloadAction } from '@reduxjs/toolkit';

export type ThemeModePreference = 'light' | 'dark' | 'system';

interface UiState {
  themeMode: ThemeModePreference;
  /** Collapsed/expanded drawer groups, keyed `<mode>:<label>`. Absent = open. */
  navOpenGroups: Record<string, boolean>;
  /** Where "← Back to EnvManager" returns to from admin mode. */
  lastAppRoute: string;
}

const STORAGE_KEY = 'ui.themeMode';
const NAV_GROUPS_KEY = 'ui.navOpenGroups';

function readInitialMode(): ThemeModePreference {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') return stored;
  return 'system';
}

// localStorage can be absent (thumbnail capture), blocked, or hold garbage —
// none of which may stop the drawer rendering. Default is "everything open".
function readNavGroups(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(NAV_GROUPS_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeNavGroups(groups: Record<string, boolean>): void {
  try {
    localStorage.setItem(NAV_GROUPS_KEY, JSON.stringify(groups));
  } catch {
    /* persistence is a convenience, never a requirement */
  }
}

const initialState: UiState = {
  themeMode: readInitialMode(),
  navOpenGroups: readNavGroups(),
  lastAppRoute: '/dashboard',
};

const uiSlice = createSlice({
  name: 'ui',
  initialState,
  reducers: {
    setThemeMode(state, action: PayloadAction<ThemeModePreference>) {
      state.themeMode = action.payload;
      localStorage.setItem(STORAGE_KEY, action.payload);
    },
    setNavGroupOpen(state, action: PayloadAction<{ key: string; open: boolean }>) {
      state.navOpenGroups[action.payload.key] = action.payload.open;
      writeNavGroups(state.navOpenGroups);
    },
    setLastAppRoute(state, action: PayloadAction<string>) {
      state.lastAppRoute = action.payload;
    },
  },
});

export const { setThemeMode, setNavGroupOpen, setLastAppRoute } = uiSlice.actions;
export default uiSlice.reducer;
