import { Button, Container, Stack, Typography } from '@mui/material'
import { useNavigate } from 'react-router-dom'

export default function NotFound() {
    const navigate = useNavigate()
    return (
        <Container maxWidth="sm" sx={{ py: 8 }}>
            <Stack spacing={2} alignItems="flex-start">
                <Typography variant="h3" component="h1">
                    404
                </Typography>
                <Typography variant="h6" color="text.secondary">
                    Page not found
                </Typography>
                <Typography variant="body1" color="text.secondary">
                    The page you were looking for doesn't exist or has moved.
                </Typography>
                <Button variant="contained" onClick={() => navigate('/')}>
                    Back home
                </Button>
            </Stack>
        </Container>
    )
}
