import { createTheme } from '@mui/material/styles'

export const theme = createTheme({
    palette: {
        mode: 'light',
        primary: {
            main: '#1976d2',
        },
        secondary: {
            main: '#dc004e',
        },
    },
    typography: {
        fontFamily: [
            '-apple-system',
            'BlinkMacSystemFont',
            '"Segoe UI"',
            'Roboto',
            '"Helvetica Neue"',
            'Arial',
            'sans-serif',
        ].join(','),
    },
    components: {
        MuiDialogContent: {
            styleOverrides: {
                root: {
                    // overflow: auto clips the absolutely-positioned floating label on the first field
                    overflowY: 'visible',
                    // Restore scrolling on the Paper instead (handled by Dialog's scroll="paper" default)
                },
            },
        },
        MuiDialog: {
            defaultProps: {
                PaperProps: {
                    sx: { overflowY: 'auto' },
                },
            },
        },
    },
})
