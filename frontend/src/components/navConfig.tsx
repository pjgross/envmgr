import type { ReactNode } from 'react';
import DashboardIcon from '@mui/icons-material/Dashboard';
import QueryStatsIcon from '@mui/icons-material/QueryStats';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ComputerIcon from '@mui/icons-material/Computer';
import CompareArrowsIcon from '@mui/icons-material/CompareArrows';
import StorageIcon from '@mui/icons-material/Storage';
import UploadIcon from '@mui/icons-material/Upload';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import CalendarMonthIcon from '@mui/icons-material/CalendarMonth';
import ListIcon from '@mui/icons-material/List';
import BuildIcon from '@mui/icons-material/Build';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import TimelineIcon from '@mui/icons-material/Timeline';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import ScheduleIcon from '@mui/icons-material/Schedule';
import InsightsIcon from '@mui/icons-material/Insights';
import BugReportIcon from '@mui/icons-material/BugReport';
import FactCheckIcon from '@mui/icons-material/FactCheck';
import HealthAndSafetyIcon from '@mui/icons-material/HealthAndSafety';
import AssignmentIcon from '@mui/icons-material/Assignment';
import GavelIcon from '@mui/icons-material/Gavel';
import DeleteSweepIcon from '@mui/icons-material/DeleteSweep';
import FolderIcon from '@mui/icons-material/Folder';
import WorkspacesIcon from '@mui/icons-material/Workspaces';
import InboxIcon from '@mui/icons-material/Inbox';

/** Minimal user shape the nav needs — decoupled from the store's User type. */
export interface NavUser {
  role?: string;
  is_master_admin?: boolean;
}

export type NavRole = 'admin' | 'masterAdmin' | 'adminOrMaster';

/** Keys a `NavItem` can hand off to a badge data source (Task 7 introduces the first one). */
export type NavBadgeKey = 'my-work';

export interface NavItem {
  label: string;
  path: string;
  icon?: ReactNode;
  requires?: NavRole;
  /** One line for the /admin hub cards. Unused in the app tree. */
  description?: string;
  /** Looked up in `NavDrawerProps.badges` by whoever renders the tree — see NavDrawer.tsx. */
  badge?: NavBadgeKey;
}

export interface NavGroup {
  label: string;
  icon: ReactNode;
  requires?: NavRole;
  children: NavItem[];
}

export type NavEntry = NavItem | NavGroup;

export function isNavGroup(entry: NavEntry): entry is NavGroup {
  return 'children' in entry;
}

export const ADMIN_ROOT = '/admin';

export function userSatisfies(user: NavUser | null, requires?: NavRole): boolean {
  if (!requires) return true;
  const isAdmin = user?.role === 'Admin';
  const isMaster = user?.is_master_admin === true;
  if (requires === 'admin') return isAdmin;
  if (requires === 'masterAdmin') return isMaster;
  return isAdmin || isMaster;
}

/**
 * The app tree. Order here is the render order. Labels are sentence case and
 * never repeat their group's name — the group header already says it.
 *
 * Deliberately absent: "Release templates" (admin configuration, see
 * adminNavConfig).
 */
export const appNav: NavEntry[] = [
  { label: 'Dashboard', path: '/dashboard', icon: <DashboardIcon /> },
  // Ungrouped and top-level, next to Dashboard — one click from anywhere.
  // `badge: 'my-work'` is looked up against live data by whoever renders
  // this tree (AppLayout supplies it to NavDrawer); nothing here is wired to
  // a data source, keeping this file pure declaration.
  { label: 'My work', path: '/my-work', icon: <InboxIcon />, badge: 'my-work' },
  {
    label: 'Catalogue',
    icon: <AccountTreeIcon />,
    children: [
      { label: 'Systems', path: '/systems', icon: <AccountTreeIcon /> },
      { label: 'Environments', path: '/environments', icon: <ComputerIcon /> },
      { label: 'Hosts', path: '/infrastructure/hosts', icon: <StorageIcon /> },
      { label: 'Compare environments', path: '/environments/compare', icon: <CompareArrowsIcon /> },
      { label: 'Import', path: '/import', icon: <UploadIcon /> },
    ],
  },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    children: [
      { label: 'Calendar', path: '/bookings/calendar', icon: <CalendarMonthIcon /> },
      { label: 'List', path: '/bookings/list', icon: <ListIcon /> },
      { label: 'Environment requests', path: '/environment-requests', icon: <AssignmentIcon /> },
      { label: 'Change requests', path: '/change-requests', icon: <BuildIcon /> },
      // Readable by any tenant member; writes stay Admin-gated on the page.
      { label: 'Projects', path: '/projects', icon: <FolderIcon /> },
      { label: 'Environment groups', path: '/environment-groups', icon: <WorkspacesIcon /> },
      // Worklists readable by any tenant member: who may ACT on a row is
      // settled on the row, not by hiding the page.
      { label: 'Contentions', path: '/contentions', icon: <GavelIcon /> },
      { label: 'Decommissions', path: '/decommissions', icon: <DeleteSweepIcon /> },
    ],
  },
  {
    label: 'Releases',
    icon: <RocketLaunchIcon />,
    children: [
      { label: 'List', path: '/releases', icon: <ListIcon /> },
      { label: 'Calendar', path: '/releases/calendar', icon: <CalendarMonthIcon /> },
      { label: 'Timeline', path: '/releases/timeline', icon: <TimelineIcon /> },
      { label: 'Scope windows', path: '/releases/scope-windows', icon: <ScheduleIcon /> },
      { label: 'Analytics', path: '/releases/analytics', icon: <InsightsIcon /> },
      { label: 'Builds', path: '/builds', icon: <BuildIcon /> },
      { label: 'Deployments', path: '/deployments', icon: <RocketLaunchIcon /> },
      { label: 'Incidents', path: '/incidents', icon: <BugReportIcon /> },
      { label: 'PIR actions', path: '/pir-actions', icon: <FactCheckIcon /> },
    ],
  },
  {
    label: 'Insights',
    icon: <QueryStatsIcon />,
    children: [
      { label: 'DORA metrics', path: '/insights/dora', icon: <QueryStatsIcon /> },
      { label: 'Environment health', path: '/insights/health', icon: <HealthAndSafetyIcon /> },
    ],
  },
  {
    label: 'Administration',
    path: ADMIN_ROOT,
    icon: <AdminPanelSettingsIcon />,
    // A master admin who is not role Admin still needs the Platform section.
    requires: 'adminOrMaster',
  },
];

/** Filter by role; drop any group left with no children. */
export function visibleAppNav(user: NavUser | null): NavEntry[] {
  const out: NavEntry[] = [];
  for (const entry of appNav) {
    if (!userSatisfies(user, entry.requires)) continue;
    if (isNavGroup(entry)) {
      const children = entry.children.filter((c) => userSatisfies(user, c.requires));
      if (children.length > 0) out.push({ ...entry, children });
    } else {
      out.push(entry);
    }
  }
  return out;
}
