import { Box, Button, Container, Stack, Typography } from '@mui/material'
import type { FallbackProps } from 'react-error-boundary'

function messageFor(error: unknown): string {
    if (error instanceof Error) return error.message
    if (typeof error === 'string') return error
    try {
        return JSON.stringify(error)
    } catch {
        return 'Unknown error'
    }
}

export default function ErrorFallback({ error, resetErrorBoundary }: FallbackProps) {
    return (
        <Container maxWidth="sm" sx={{ py: 6 }}>
            <Stack spacing={2} alignItems="flex-start">
                <Typography variant="h5" component="h1">
                    Something went wrong.
                </Typography>
                <Typography variant="body1" color="text.secondary">
                    The page hit an unexpected error. Try reloading; if it persists, let us know.
                </Typography>
                <Box
                    component="pre"
                    sx={{
                        p: 2,
                        bgcolor: 'action.hover',
                        borderRadius: 1,
                        width: '100%',
                        overflowX: 'auto',
                        fontSize: 12,
                        whiteSpace: 'pre-wrap',
                    }}
                >
                    {messageFor(error)}
                </Box>
                <Stack direction="row" spacing={1}>
                    <Button variant="contained" onClick={resetErrorBoundary}>
                        Try again
                    </Button>
                    <Button variant="outlined" onClick={() => window.location.reload()}>
                        Reload page
                    </Button>
                </Stack>
            </Stack>
        </Container>
    )
}
