import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  Box, Divider, Drawer, List, ListItemButton,
  ListItemIcon, ListItemText, Toolbar, Typography,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import PeopleIcon from '@mui/icons-material/People';
import StorageIcon from '@mui/icons-material/Storage';
import MemoryIcon from '@mui/icons-material/Memory';
import LanguageIcon from '@mui/icons-material/Language';
import EventIcon from '@mui/icons-material/Event';

const DRAWER_WIDTH = 220;

const adminNavItems = [
  { label: 'General Settings', path: '/tenant/settings', icon: <SettingsIcon fontSize="small" /> },
  { label: 'User Management', path: '/tenant/users', icon: <PeopleIcon fontSize="small" /> },
];

const entityNavItems = [
  { label: 'Systems', path: '/admin/config/system', icon: <StorageIcon fontSize="small" /> },
  { label: 'Subsystems', path: '/admin/config/subsystem', icon: <MemoryIcon fontSize="small" /> },
  { label: 'Environments', path: '/admin/config/environment', icon: <LanguageIcon fontSize="small" /> },
  { label: 'Bookings', path: '/admin/config/booking', icon: <EventIcon fontSize="small" /> },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const { pathname } = useLocation();

  return (
    <Box sx={{ display: 'flex' }}>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': { width: DRAWER_WIDTH, boxSizing: 'border-box', position: 'relative', height: '100%' },
        }}
      >
        <Toolbar />
        <Box sx={{ overflow: 'auto', p: 1 }}>
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>Admin</Typography>
          <List dense>
            {adminNavItems.map((item) => (
              <ListItemButton
                key={item.path}
                selected={pathname === item.path}
                onClick={() => navigate(item.path)}
              >
                <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            ))}
          </List>
          <Divider sx={{ my: 1 }} />
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>Entity Config</Typography>
          <List dense>
            {entityNavItems.map((item) => (
              <ListItemButton
                key={item.path}
                selected={pathname === item.path}
                onClick={() => navigate(item.path)}
              >
                <ListItemIcon sx={{ minWidth: 32 }}>{item.icon}</ListItemIcon>
                <ListItemText primary={item.label} />
              </ListItemButton>
            ))}
          </List>
        </Box>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, overflow: 'auto' }}>
        <Outlet />
      </Box>
    </Box>
  );
}
