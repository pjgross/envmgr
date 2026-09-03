import { useEffect, useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { useNavigate, useLocation, Outlet, Link as RouterLink } from 'react-router-dom';
import {
  AppBar,
  Box,
  Divider,
  Drawer,
  IconButton,
  Link,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Toolbar,
  Typography,
  Avatar,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { ErrorBoundary } from 'react-error-boundary';
import MenuIcon from '@mui/icons-material/Menu';
import LogoutIcon from '@mui/icons-material/Logout';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import Brightness4Icon from '@mui/icons-material/Brightness4';
import Brightness7Icon from '@mui/icons-material/Brightness7';
import SettingsBrightnessIcon from '@mui/icons-material/SettingsBrightness';
import { RootState } from '../store';
import { authService } from '../services/authService';
import { logout } from '../store/authSlice';
import { setLastAppRoute, setNavGroupOpen, setThemeMode, type ThemeModePreference } from '../store/uiSlice';
import ErrorFallback from './ErrorFallback';
import { ADMIN_ROOT, visibleAppNav } from './navConfig';
import { visibleAdminNav } from './adminNavConfig';
import NavDrawer, { groupContaining } from './NavDrawer';

const DRAWER_WIDTH = 240;

export default function AppLayout() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const user = useSelector((state: RootState) => state.auth.user);
  const themeMode = useSelector((state: RootState) => state.ui.themeMode);
  const navOpenGroups = useSelector((state: RootState) => state.ui.navOpenGroups);
  const lastAppRoute = useSelector((state: RootState) => state.ui.lastAppRoute);
  const muiTheme = useTheme();
  const isDesktop = useMediaQuery(muiTheme.breakpoints.up('md'));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [menuAnchor, setMenuAnchor] = useState<null | HTMLElement>(null);

  const adminMode =
    location.pathname === ADMIN_ROOT || location.pathname.startsWith(ADMIN_ROOT + '/');
  const mode = adminMode ? 'admin' : 'app';
  const entries = adminMode ? visibleAdminNav(user) : visibleAppNav(user);
  const groupKey = (label: string) => `${mode}:${label}`;
  const isGroupOpen = (label: string) => navOpenGroups[groupKey(label)] ?? true;
  const toggleGroup = (label: string) =>
    dispatch(setNavGroupOpen({ key: groupKey(label), open: !isGroupOpen(label) }));

  const closeMobileDrawer = () => {
    if (!isDesktop) setMobileOpen(false);
  };

  const navigateAndClose = (path: string) => {
    navigate(path);
    closeMobileDrawer();
  };

  // Open the group holding the current route on EVERY navigation, and remember
  // the last non-admin route so "Back to EnvManager" has somewhere to go.
  useEffect(() => {
    if (!adminMode) dispatch(setLastAppRoute(location.pathname + location.search));
    const holder = groupContaining(entries, location.pathname);
    if (holder !== undefined && navOpenGroups[groupKey(holder)] === false) {
      dispatch(setNavGroupOpen({ key: groupKey(holder), open: true }));
    }
    // navOpenGroups is derived from the store and read fresh on every call, so
    // it's deliberately left out of the deps; `user` IS a dep because `entries`
    // is computed from it — on a hard reload straight onto an admin deep link,
    // the first run sees a null user (so visibleAdminNav(null) has almost
    // nothing in it) and must re-run once the real user arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.search, adminMode, user]);

  const handleLogout = async () => {
    setMenuAnchor(null);
    // Revoke server-side first, while the refresh token is still in storage —
    // clearing local state first would leave the session alive on the server,
    // which is the bug this whole flow exists to fix. Best-effort: local state is
    // cleared regardless, so a failed call cannot trap the user signed in.
    await authService.logout();
    dispatch(logout());
    navigate('/login');
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

  const adminHeader = (
    <>
      <ListItemButton onClick={() => navigateAndClose(lastAppRoute)} sx={{ borderRadius: 1, mx: 1, mt: 0.5 }}>
        <ListItemIcon sx={{ minWidth: 36 }}><ArrowBackIcon fontSize="small" /></ListItemIcon>
        <ListItemText primary="Back to EnvManager" />
      </ListItemButton>
      <Link
        component={RouterLink}
        to={ADMIN_ROOT}
        onClick={closeMobileDrawer}
        color="text.secondary"
        underline="none"
        variant="overline"
        sx={{ px: 2, display: 'block' }}
      >
        Administration
      </Link>
    </>
  );

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
          <Link
            component={RouterLink}
            to="/dashboard"
            color="inherit"
            underline="none"
            variant="h6"
            sx={{ flexGrow: 1 }}
          >
            EnvManager
          </Link>
          <IconButton color="inherit" aria-label="Account menu" onClick={(e) => setMenuAnchor(e.currentTarget)}>
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
          <NavDrawer
            entries={entries}
            currentPath={location.pathname}
            isGroupOpen={isGroupOpen}
            onToggleGroup={toggleGroup}
            onNavigate={navigateAndClose}
            header={adminMode ? adminHeader : undefined}
          />
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
