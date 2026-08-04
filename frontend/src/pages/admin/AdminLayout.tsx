import { useNavigate, useLocation, Outlet } from 'react-router-dom';
import {
  Box,
  Divider,
  Drawer,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
} from '@mui/material';
import SettingsIcon from '@mui/icons-material/Settings';
import PeopleIcon from '@mui/icons-material/People';
import GroupsIcon from '@mui/icons-material/Groups';
import StorageIcon from '@mui/icons-material/Storage';
import MemoryIcon from '@mui/icons-material/Memory';
import LanguageIcon from '@mui/icons-material/Language';
import EventIcon from '@mui/icons-material/Event';
import CategoryIcon from '@mui/icons-material/Category';
import BuildIcon from '@mui/icons-material/Build';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import BugReportIcon from '@mui/icons-material/BugReport';

const DRAWER_WIDTH = 220;

const adminNavItems = [
  { label: 'General Settings', path: '/tenant/settings', icon: <SettingsIcon fontSize="small" /> },
  { label: 'User Management', path: '/tenant/users', icon: <PeopleIcon fontSize="small" /> },
  { label: 'User Groups', path: '/tenant/groups', icon: <GroupsIcon fontSize="small" /> },
  { label: 'API keys', path: '/tenant/api-keys', icon: <VpnKeyIcon fontSize="small" /> },
  { label: 'RAID Settings', path: '/tenant/raid-settings', icon: <WarningAmberIcon fontSize="small" /> },
];

const entityNavItems = [
  { label: 'Systems', path: '/admin/config/system', icon: <StorageIcon fontSize="small" /> },
  { label: 'Subsystems', path: '/admin/config/subsystem', icon: <MemoryIcon fontSize="small" /> },
  {
    label: 'Component Types',
    path: '/admin/config/component-types',
    icon: <CategoryIcon fontSize="small" />,
  },
  {
    label: 'Environments',
    path: '/admin/config/environment',
    icon: <LanguageIcon fontSize="small" />,
  },
  { label: 'Bookings', path: '/admin/config/booking', icon: <EventIcon fontSize="small" /> },
  {
    label: 'Change Requests',
    path: '/admin/config/change-request',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Releases',
    path: '/admin/config/release',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Release scope item',
    path: '/admin/config/release-change',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Builds',
    path: '/admin/config/build',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Deployments',
    path: '/admin/config/deployment',
    icon: <BuildIcon fontSize="small" />,
  },
  {
    label: 'Incidents',
    path: '/admin/config/incident',
    icon: <BugReportIcon fontSize="small" />,
  },
  {
    label: 'Scope change rules',
    path: '/admin/scope-change-rules',
    icon: <BuildIcon fontSize="small" />,
  },
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
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            position: 'relative',
            height: '100%',
          },
        }}
      >
        <Box sx={{ overflow: 'auto', p: 1 }}>
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>
            Admin
          </Typography>
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
          <Typography variant="overline" color="text.secondary" sx={{ px: 1 }}>
            Entity Config
          </Typography>
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
