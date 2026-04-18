import { createSlice, PayloadAction } from '@reduxjs/toolkit'

export type ThemeModePreference = 'light' | 'dark' | 'system'

interface UiState {
    themeMode: ThemeModePreference
}

const STORAGE_KEY = 'ui.themeMode'

function readInitialMode(): ThemeModePreference {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
    return 'system'
}

const initialState: UiState = {
    themeMode: readInitialMode(),
}

const uiSlice = createSlice({
    name: 'ui',
    initialState,
    reducers: {
        setThemeMode(state, action: PayloadAction<ThemeModePreference>) {
            state.themeMode = action.payload
            localStorage.setItem(STORAGE_KEY, action.payload)
        },
    },
})

export const { setThemeMode } = uiSlice.actions
export default uiSlice.reducer
