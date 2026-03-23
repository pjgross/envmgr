import { useState } from 'react'
import { useSelector, useDispatch } from 'react-redux'
import { useNavigate, Outlet } from 'react-router-dom'
import {
    AppBar,
    Toolbar,
    Typography,
    Box,
    IconButton,
    Menu,
    MenuItem,
    Divider,
    ListItemIcon,
    ListItemText,
    Avatar,
} from '@mui/material'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings'
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts'
import LogoutIcon from '@mui/icons-material/Logout'
import { RootState } from '../store'
import { logout } from '../store/authSlice'

export default function AppLayout() {
    const dispatch = useDispatch()
    const navigate = useNavigate()
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
        <Box>
            <AppBar position="static">
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
            <Outlet />
        </Box>
    )
}
