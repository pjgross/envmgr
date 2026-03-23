import { useState } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { useNavigate, useLocation, Outlet } from 'react-router-dom'
import {
    AppBar,
    Box,
    Chip,
    Divider,
    Drawer,
    IconButton,
    List,
    ListItemButton,
    ListItemIcon,
    ListItemText,
    Menu,
    MenuItem,
    Toolbar,
    Tooltip,
    Typography,
    Avatar,
} from '@mui/material'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings'
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts'
import LogoutIcon from '@mui/icons-material/Logout'
import DashboardIcon from '@mui/icons-material/Dashboard'
import ComputerIcon from '@mui/icons-material/Computer'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import EventAvailableIcon from '@mui/icons-material/EventAvailable'
import UploadIcon from '@mui/icons-material/Upload'
import { RootState } from '../store'
import { logout } from '../store/authSlice'

const DRAWER_WIDTH = 240

interface NavItem {
  label: string
  path: string
  icon: React.ReactNode
  comingSoon?: boolean
}

const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
  { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
  { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
  { label: 'Bookings', path: '/bookings', icon: <EventAvailableIcon /> },
  { label: 'Import', path: '/import', icon: <UploadIcon /> },
]

export default function AppLayout() {
    const dispatch = useDispatch()
    const navigate = useNavigate()
    const location = useLocation()
    const user = useSelector((state: RootState) => state.auth.user)
    const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null)

    const handleLogout = () => {
        setMenuAnchor(null)
        dispatch(logout())
        navigate('/login')
    }

    const handleMenuNav = (path: string) => {
        setMenuAnchor(null)
        navigate(path)
    }

    return (
        <Box sx={{ display: 'flex' }}>
            {/* Top AppBar */}
            <AppBar
                position="fixed"
                sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}
            >
                <Toolbar>
                    <Typography
                        variant="h6"
                        component="div"
                        sx={{ flexGrow: 1, cursor: 'pointer' }}
                        onClick={() => navigate('/dashboard')}
                    >
                        EnvManager
                    </Typography>
                    <IconButton color="inherit" onClick={(e) => setMenuAnchor(e.currentTarget)}>
                        <Avatar sx={{ width: 32, height: 32, bgcolor: 'primary.dark', fontSize: 14 }}>
                            {user?.username?.[0]?.toUpperCase()}
                        </Avatar>
                    </IconButton>
                    <Menu
                        anchorEl={menuAnchor}
                        open={Boolean(menuAnchor)}
                        onClose={() => setMenuAnchor(null)}
                        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
                        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
                    >
                        <Box sx={{ px: 2, py: 1.5, minWidth: 220 }}>
                            <Typography variant="subtitle2" fontWeight="bold">
                                {user?.username}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {user?.email}
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {user?.role}{user?.is_master_admin ? ' · Master Admin' : ''}
                            </Typography>
                        </Box>
                        <Divider />
                        {user?.is_master_admin && (
                            <MenuItem onClick={() => handleMenuNav('/admin/tenants')}>
                                <ListItemIcon><AdminPanelSettingsIcon fontSize="small" /></ListItemIcon>
                                <ListItemText>Platform Admin</ListItemText>
                            </MenuItem>
                        )}
                        {user?.role === 'Admin' && (
                            <MenuItem onClick={() => handleMenuNav('/tenant/users')}>
                                <ListItemIcon><ManageAccountsIcon fontSize="small" /></ListItemIcon>
                                <ListItemText>Tenant Admin</ListItemText>
                            </MenuItem>
                        )}
                        {(user?.is_master_admin || user?.role === 'Admin') && <Divider />}
                        <MenuItem onClick={handleLogout}>
                            <ListItemIcon><LogoutIcon fontSize="small" /></ListItemIcon>
                            <ListItemText>Logout</ListItemText>
                        </MenuItem>
                    </Menu>
                </Toolbar>
            </AppBar>

            {/* Persistent sidebar Drawer */}
            <Drawer
                variant="permanent"
                sx={{
                    width: DRAWER_WIDTH,
                    flexShrink: 0,
                    '& .MuiDrawer-paper': {
                        width: DRAWER_WIDTH,
                        boxSizing: 'border-box',
                    },
                }}
            >
                {/* Offset for AppBar height */}
                <Toolbar />
                <Box sx={{ overflow: 'auto', mt: 1 }}>
                    <List dense>
                        {navItems.map((item) => {
                            const isActive = location.pathname === item.path ||
                                (item.path !== '/dashboard' && location.pathname.startsWith(item.path))
                            return (
                                <Tooltip
                                    key={item.path}
                                    title={item.comingSoon ? 'Coming soon' : ''}
                                    placement="right"
                                >
                                    <span>
                                        <ListItemButton
                                            selected={isActive}
                                            disabled={item.comingSoon}
                                            onClick={() => !item.comingSoon && navigate(item.path)}
                                            sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
                                        >
                                            <ListItemIcon sx={{ minWidth: 36 }}>
                                                {item.icon}
                                            </ListItemIcon>
                                            <ListItemText primary={item.label} />
                                            {item.comingSoon && (
                                                <Chip
                                                    label="Soon"
                                                    size="small"
                                                    sx={{ height: 18, fontSize: 10 }}
                                                />
                                            )}
                                        </ListItemButton>
                                    </span>
                                </Tooltip>
                            )
                        })}
                    </List>
                </Box>
            </Drawer>

            {/* Main content area — offset by drawer width */}
            <Box
                component="main"
                sx={{
                    flexGrow: 1,
                    minHeight: '100vh',
                    bgcolor: 'background.default',
                }}
            >
                <Toolbar />
                <Outlet />
            </Box>
        </Box>
    )
}
