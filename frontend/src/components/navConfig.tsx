import type { ReactNode } from 'react';
import DashboardIcon from '@mui/icons-material/Dashboard';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ComputerIcon from '@mui/icons-material/Computer';
import StorageIcon from '@mui/icons-material/Storage';
import UploadIcon from '@mui/icons-material/Upload';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import ListIcon from '@mui/icons-material/List';
import BuildIcon from '@mui/icons-material/Build';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import TimelineIcon from '@mui/icons-material/Timeline';
import LibraryBooksIcon from '@mui/icons-material/LibraryBooks';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ManageAccountsIcon from '@mui/icons-material/ManageAccounts';
import SettingsIcon from '@mui/icons-material/Settings';
import TuneIcon from '@mui/icons-material/Tune';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import VpnKeyIcon from '@mui/icons-material/VpnKey';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InsightsIcon from '@mui/icons-material/Insights';
import BugReportIcon from '@mui/icons-material/BugReport';

/** Minimal user shape the nav needs — decoupled from the store's User type. */
export interface NavUser {
  role?: string;
  is_master_admin?: boolean;
}

export type NavRole = 'admin' | 'masterAdmin';

export interface NavItem {
  label: string;
  path?: string; // group headers have no path
  icon: ReactNode;
  comingSoon?: boolean;
  requires?: NavRole;
  defaultOpen?: boolean; // group starts expanded
  children?: NavItem[];
}

/** The full, unfiltered menu. Order here is the render order. */
export const navGroups: NavItem[] = [
  {
    label: 'Insights',
    icon: <QueryStatsIcon />,
    defaultOpen: true,
    children: [
      { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
      { label: 'DORA Metrics', path: '/insights/dora', icon: <QueryStatsIcon />, comingSoon: true },
    ],
  },
  {
    label: 'Environment Definition',
    icon: <AccountTreeIcon />,
    children: [
      { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
      { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
      { label: 'Hosts', path: '/infrastructure/hosts', icon: <StorageIcon /> },
      { label: 'Import', path: '/import', icon: <UploadIcon /> },
    ],
  },
  {
    label: 'Environment Management',
    icon: <EventAvailableIcon />,
    children: [
      { label: 'Bookings — Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Bookings — List', path: '/bookings/list', icon: <ListIcon /> },
      { label: 'Change Requests', path: '/change-requests', icon: <BuildIcon /> },
    ],
  },
  {
    label: 'Release Management',
    icon: <RocketLaunchIcon />,
    children: [
      { label: 'Releases — List', path: '/releases', icon: <ListIcon /> },
      { label: 'Releases — Calendar', path: '/releases/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Releases — Timeline', path: '/releases/timeline', icon: <TimelineIcon /> },
      { label: 'Releases — Scope Windows', path: '/releases/scope-windows', icon: <ScheduleIcon /> },
      { label: 'Releases — Analytics', path: '/releases/analytics', icon: <InsightsIcon /> },
      {
        label: 'Release Templates',
        path: '/admin/release-templates',
        icon: <LibraryBooksIcon />,
        requires: 'admin',
      },
      { label: 'Builds', path: '/builds', icon: <BuildIcon /> },
      { label: 'Deployments', path: '/deployments', icon: <RocketLaunchIcon /> },
      { label: 'Incidents', path: '/incidents', icon: <BugReportIcon /> },
    ],
  },
  {
    label: 'Administration',
    icon: <AdminPanelSettingsIcon />,
    // No `requires` — visible whenever it has >=1 visible child, so a
    // master-admin who is not role 'Admin' still sees Platform Admin.
    children: [
      { label: 'Users', path: '/tenant/users', icon: <ManageAccountsIcon />, requires: 'admin' },
      { label: 'Tenant Settings', path: '/tenant/settings', icon: <SettingsIcon />, requires: 'admin' },
      { label: 'Change Config', path: '/admin/config/booking', icon: <TuneIcon />, requires: 'admin' },
      { label: 'RAID Settings', path: '/tenant/raid-settings', icon: <WarningAmberIcon />, requires: 'admin' },
      { label: 'API Keys', path: '/tenant/api-keys', icon: <VpnKeyIcon />, requires: 'admin' },
      { label: 'Platform Admin', path: '/admin/tenants', icon: <AdminPanelSettingsIcon />, requires: 'masterAdmin' },
    ],
  },
];

export function userSatisfies(user: NavUser | null, requires?: NavRole): boolean {
  if (!requires) return true;
  if (requires === 'admin') return user?.role === 'Admin';
  return user?.is_master_admin === true;
}

/** Filter groups + children by role. Drops any group left with no children. */
export function visibleNavGroups(user: NavUser | null): NavItem[] {
  return navGroups
    .map((group) => ({
      ...group,
      children: (group.children ?? []).filter((child) => userSatisfies(user, child.requires)),
    }))
    .filter((group) => userSatisfies(user, group.requires) && group.children.length > 0);
}
