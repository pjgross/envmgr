import { useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  AppBar,
  Box,
  Chip,
  Collapse,
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
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { ErrorBoundary } from 'react-error-boundary';
import MenuIcon from '@mui/icons-material/Menu';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts';
import LogoutIcon from '@mui/icons-material/Logout';
import DashboardIcon from '@mui/icons-material/Dashboard';
import ComputerIcon from '@mui/icons-material/Computer';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import UploadIcon from '@mui/icons-material/Upload';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import ListIcon from '@mui/icons-material/List';
import BuildIcon from '@mui/icons-material/Build';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import SettingsBrightnessIcon from '@mui/icons-material/SettingsBrightness';
import { RootState } from '../store';
import { logout } from '../store/authSlice';
import { setThemeMode, type ThemeModePreference } from '../store/uiSlice';
import ErrorFallback from './ErrorFallback';

const DRAWER_WIDTH = 240;

interface NavItem {
  label: string;
  path?: string; // optional: group items have no path
  icon: React.ReactNode;
  comingSoon?: boolean;
  children?: NavItem[]; // sub-items for expandable groups
}

const navItems: NavItem[] = [
  { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
  { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
  { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    children: [
      { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
      { label: 'List', path: '/bookings/list', icon: <ListIcon /> },
    ],
  },
  { label: 'Change Requests', path: '/change-requests', icon: <BuildIcon /> },
  { label: 'Import', path: '/import', icon: <UploadIcon /> },
];

export default function AppLayout() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useSelector((state: RootState) => state.auth.user);
  const themeMode = useSelector((state: RootState) => state.ui.themeMode);
  const muiTheme = useTheme();
  const isDesktop = useMediaQuery(muiTheme.breakpoints.up('md'));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null);
  const [groupOpen, setGroupOpen] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {};
    for (const item of navItems) {
      if (item.children) {
        initial[item.label] = item.children.some(
          (child) => child.path !== undefined && location.pathname.startsWith(child.path)
        );
      }
    }
    return initial;
  });

  const closeMobileDrawer = () => {
    if (!isDesktop) setMobileOpen(false);
  };

  const navigateAndClose = (path: string) => {
    navigate(path);
    closeMobileDrawer();
  };

  const handleLogout = () => {
    setMenuAnchor(null);
    dispatch(logout());
    navigate('/login');
  };

  const handleMenuNav = (path: string) => {
    setMenuAnchor(null);
    navigate(path);
  };

  const cycleThemeMode = () => {
    const next: Record<ThemeModePreference, ThemeModePreference> = {
      light: 'dark',
      dark: 'system',
      system: 'light',
    };
    dispatch(setThemeMode(next[themeMode]));
  };

  const themeIcon =
    themeMode === 'light' ? (
      <Brightness7Icon fontSize="small" />
    ) : themeMode === 'dark' ? (
      <Brightness4Icon fontSize="small" />
    ) : (
      <SettingsBrightnessIcon fontSize="small" />
    );
  const themeLabel =
    themeMode === 'light' ? 'Light mode' : themeMode === 'dark' ? 'Dark mode' : 'System theme';

  return (
    <Box sx={{ display: 'flex' }}>
      {/* Top AppBar */}
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar>
          {!isDesktop && (
            <IconButton
              color="inherit"
              edge="start"
              onClick={() => setMobileOpen((open) => !open)}
              aria-label="Toggle navigation"
              sx={{ mr: 1 }}
            >
              <MenuIcon />
            </IconButton>
          )}
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
                {user?.role}
                {user?.is_master_admin ? ' · Master Admin' : ''}
              </Typography>
            </Box>
            <Divider />
            {user?.is_master_admin && (
              <MenuItem onClick={() => handleMenuNav('/admin/tenants')}>
                <ListItemIcon>
                  <AdminPanelSettingsIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Platform Admin</ListItemText>
              </MenuItem>
            )}
            {user?.role === 'Admin' && (
              <MenuItem onClick={() => handleMenuNav('/tenant/users')}>
                <ListItemIcon>
                  <ManageAccountsIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Tenant Admin</ListItemText>
              </MenuItem>
            )}
            {(user?.is_master_admin || user?.role === 'Admin') && <Divider />}
            <MenuItem onClick={cycleThemeMode}>
              <ListItemIcon>{themeIcon}</ListItemIcon>
              <ListItemText>{themeLabel}</ListItemText>
            </MenuItem>
            <Divider />
            <MenuItem onClick={handleLogout}>
              <ListItemIcon>
                <LogoutIcon fontSize="small" />
              </ListItemIcon>
              <ListItemText>Logout</ListItemText>
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>

      {/* Sidebar Drawer — permanent on md+, temporary below */}
      <Drawer
        variant={isDesktop ? 'permanent' : 'temporary'}
        open={isDesktop ? true : mobileOpen}
        onClose={() => setMobileOpen(false)}
        ModalProps={{ keepMounted: true }}
        sx={{
          width: isDesktop ? DRAWER_WIDTH : 0,
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
              if (item.children) {
                // Group item — expandable, no navigation on parent click
                const isOpen = groupOpen[item.label] ?? false;
                return (
                  <div key={item.label}>
                    <ListItemButton
                      selected={false}
                      onClick={() =>
                        setGroupOpen((prev) => ({ ...prev, [item.label]: !prev[item.label] }))
                      }
                      sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
                    >
                      <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
                      <ListItemText primary={item.label} />
                      {isOpen ? (
                        <ExpandLessIcon fontSize="small" />
                      ) : (
                        <ExpandMoreIcon fontSize="small" />
                      )}
                    </ListItemButton>
                    <Collapse in={isOpen} timeout="auto" unmountOnExit>
                      <List dense disablePadding>
                        {item.children.map((child) => {
                          const isChildActive =
                            child.path !== undefined &&
                            (location.pathname === child.path ||
                              location.pathname.startsWith(child.path + '/'));
                          return (
                            <ListItemButton
                              key={child.label}
                              selected={isChildActive}
                              onClick={() => child.path && navigateAndClose(child.path)}
                              sx={{ borderRadius: 1, mx: 1, mb: 0.5, pl: 4 }}
                            >
                              <ListItemIcon sx={{ minWidth: 36 }}>{child.icon}</ListItemIcon>
                              <ListItemText primary={child.label} />
                            </ListItemButton>
                          );
                        })}
                      </List>
                    </Collapse>
                  </div>
                );
              }

              // Leaf item — original behaviour
              const isActive =
                item.path !== undefined &&
                (location.pathname === item.path ||
                  (item.path !== '/dashboard' && location.pathname.startsWith(item.path)));
              return (
                <Tooltip
                  key={item.label}
                  title={item.comingSoon ? 'Coming soon' : ''}
                  placement="right"
                >
                  <span>
                    <ListItemButton
                      selected={isActive}
                      disabled={item.comingSoon}
                      onClick={() => !item.comingSoon && item.path && navigateAndClose(item.path)}
                      sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
                    >
                      <ListItemIcon sx={{ minWidth: 36 }}>{item.icon}</ListItemIcon>
                      <ListItemText primary={item.label} />
                      {item.comingSoon && (
                        <Chip label="Soon" size="small" sx={{ height: 18, fontSize: 10 }} />
                      )}
                    </ListItemButton>
                  </span>
                </Tooltip>
              );
            })}
            {user?.role === 'Admin' && (
              <ListItemButton
                selected={location.pathname.startsWith('/admin/config')}
                onClick={() => navigateAndClose('/admin/config/booking')}
                sx={{ borderRadius: 1, mx: 1, mb: 0.5 }}
              >
                <ListItemIcon sx={{ minWidth: 36 }}>
                  <AdminPanelSettingsIcon />
                </ListItemIcon>
                <ListItemText primary="Admin" />
              </ListItemButton>
            )}
          </List>
        </Box>
      </Drawer>

      {/* Main content area — offset by drawer width on desktop */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          minHeight: '100vh',
          bgcolor: 'background.default',
          width: { xs: '100%', md: `calc(100% - ${DRAWER_WIDTH}px)` },
        }}
      >
        <Toolbar />
        <ErrorBoundary FallbackComponent={ErrorFallback}>
          <Outlet />
        </ErrorBoundary>
      </Box>
    </Box>
  );
}
