import { useSelector, useDispatch } from 'react-redux'
import { useNavigate } from 'react-router-dom'
import {
    AppBar,
    Toolbar,
    Typography,
    Button,
    Container,
    Box,
    Paper,
    Grid,
} from '@mui/material'
import { RootState } from '../store'
import { logout } from '../store/authSlice'

export default function Dashboard() {
    const dispatch = useDispatch()
    const navigate = useNavigate()
    const user = useSelector((state: RootState) => state.auth.user)

    const handleLogout = () => {
        dispatch(logout())
        navigate('/login')
    }

    return (
        <Box>
            <AppBar position="static">
                <Toolbar>
                    <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
                        EnvManager
                    </Typography>
                    <Typography variant="body1" sx={{ mr: 2 }}>
                        {user?.username} ({user?.role})
                    </Typography>
                    <Button color="inherit" onClick={handleLogout}>
                        Logout
                    </Button>
                </Toolbar>
            </AppBar>

            <Container maxWidth="lg" sx={{ mt: 4 }}>
                <Typography variant="h4" gutterBottom>
                    Dashboard
                </Typography>

                <Grid container spacing={3}>
                    <Grid item xs={12} md={6} lg={3}>
                        <Paper sx={{ p: 3 }}>
                            <Typography variant="h6" gutterBottom>
                                Environments
                            </Typography>
                            <Typography variant="h3">0</Typography>
                            <Typography variant="body2" color="text.secondary">
                                Total environments
                            </Typography>
                        </Paper>
                    </Grid>

                    <Grid item xs={12} md={6} lg={3}>
                        <Paper sx={{ p: 3 }}>
                            <Typography variant="h6" gutterBottom>
                                Bookings
                            </Typography>
                            <Typography variant="h3">0</Typography>
                            <Typography variant="body2" color="text.secondary">
                                Active bookings
                            </Typography>
                        </Paper>
                    </Grid>

                    <Grid item xs={12} md={6} lg={3}>
                        <Paper sx={{ p: 3 }}>
                            <Typography variant="h6" gutterBottom>
                                Changes
                            </Typography>
                            <Typography variant="h3">0</Typography>
                            <Typography variant="body2" color="text.secondary">
                                Pending changes
                            </Typography>
                        </Paper>
                    </Grid>

                    <Grid item xs={12} md={6} lg={3}>
                        <Paper sx={{ p: 3 }}>
                            <Typography variant="h6" gutterBottom>
                                Releases
                            </Typography>
                            <Typography variant="h3">0</Typography>
                            <Typography variant="body2" color="text.secondary">
                                Active releases
                            </Typography>
                        </Paper>
                    </Grid>
                </Grid>

                <Paper sx={{ p: 3, mt: 3 }}>
                    <Typography variant="h6" gutterBottom>
                        Welcome to EnvManager
                    </Typography>
                    <Typography variant="body1">
                        This is Phase 0 of the EnvManager platform. The authentication system is now working.
                        Additional features will be added in subsequent phases:
                    </Typography>
                    <Box component="ul" sx={{ mt: 2 }}>
                        <li>Phase 1: Environment Inventory & Booking System</li>
                        <li>Phase 2: Change Management</li>
                        <li>Phase 3: Releases & Test Phases</li>
                        <li>Phase 4: CI/CD Deployment Tracking</li>
                        <li>Phase 5: DORA Metrics</li>
                        <li>Phase 6: Infrastructure Topology Visualization</li>
                        <li>Phase 7: Multi-Project Coordination</li>
                    </Box>
                </Paper>
            </Container>
        </Box>
    )
}
