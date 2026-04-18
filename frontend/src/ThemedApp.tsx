import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useSelector } from 'react-redux'
import { CssBaseline, ThemeProvider } from '@mui/material'
import type { PaletteMode } from '@mui/material'
import type { RootState } from './store'
import { createAppTheme } from './theme'

function getSystemMode(): PaletteMode {
    if (typeof window === 'undefined' || !window.matchMedia) return 'light'
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function ThemedApp({ children }: { children: ReactNode }) {
    const preference = useSelector((state: RootState) => state.ui.themeMode)
    const [systemMode, setSystemMode] = useState<PaletteMode>(getSystemMode)

    useEffect(() => {
        if (typeof window === 'undefined' || !window.matchMedia) return
        const mql = window.matchMedia('(prefers-color-scheme: dark)')
        const listener = (e: MediaQueryListEvent) => setSystemMode(e.matches ? 'dark' : 'light')
        mql.addEventListener('change', listener)
        return () => mql.removeEventListener('change', listener)
    }, [])

    const mode: PaletteMode = preference === 'system' ? systemMode : preference
    const theme = useMemo(() => createAppTheme(mode), [mode])

    return (
        <ThemeProvider theme={theme}>
            <CssBaseline />
            {children}
        </ThemeProvider>
    )
}
