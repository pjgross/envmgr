import BusinessIcon from '@mui/icons-material/Business';
import ComputerIcon from '@mui/icons-material/Computer';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import ExtensionIcon from '@mui/icons-material/Extension';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { entityTabPath } from '../pages/admin/entityConfigTabs';
import { userSatisfies, type NavGroup, type NavUser } from './navConfig';

/**
 * The admin tree. Sections group by WHAT an admin is configuring, not by
 * which table holds the setting — RAID settings and scope-change rules sit
 * beside release templates, where a release manager looks for them.
 *
 * Items carry no icons (one per section); every item has a description
 * because the /admin hub is generated from this tree.
 *
 * Role rule: everything is Admin-only except Platform (master admin) and
 * User groups (readable by any member — B3a's read/write split; a Developer
 * following a group link from a project page must still land somewhere).
 */
export const adminNav: NavGroup[] = [
  {
    label: 'Organisation',
    icon: <BusinessIcon />,
    children: [
      { label: 'Users', path: '/admin/users', requires: 'admin', description: 'Accounts, roles and access for this tenant.' },
      { label: 'User groups', path: '/admin/user-groups', description: 'Teams that operate environments and staff projects.' },
      { label: 'Tenant settings', path: '/admin/settings', requires: 'admin', description: 'Tenant name, slug and advanced settings.' },
    ],
  },
  {
    label: 'Environments',
    icon: <ComputerIcon />,
    requires: 'admin',
    children: [
      { label: 'Tiers', path: entityTabPath('environments', 'tiers'), description: 'The tier vocabulary (dev, SIT, UAT…) and per-tier idle thresholds.' },
      { label: 'Naming policy', path: entityTabPath('environments', 'naming-policy'), description: 'Name pattern, required attributes and quarantine grace.' },
      { label: 'Lifecycle & decommissioning', path: entityTabPath('environments', 'lifecycle-policy'), description: 'Idle detection, notice period and the teardown checklist.' },
      { label: 'Request lifecycle', path: entityTabPath('environment-requests', 'lifecycle'), description: 'States and transitions for environment requests.' },
      { label: 'Custom fields', path: entityTabPath('environments', 'fields'), description: 'Tenant-defined fields on every environment.' },
    ],
  },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    requires: 'admin',
    children: [
      { label: 'Booking types', path: entityTabPath('bookings', 'types'), description: 'Types, default protection level and duration presets.' },
      { label: 'Lifecycle', path: entityTabPath('bookings', 'lifecycle'), description: 'States and transitions for bookings.' },
      { label: 'Custom fields', path: entityTabPath('bookings', 'fields'), description: 'Tenant-defined fields on every booking.' },
    ],
  },
  {
    label: 'Releases',
    icon: <RocketLaunchIcon />,
    requires: 'admin',
    children: [
      { label: 'Templates', path: '/admin/releases/templates', description: 'Reusable release blueprints: phases, gates and events.' },
      { label: 'Gate types', path: entityTabPath('releases', 'gate-types'), description: 'The gate vocabulary, failure behaviour and expected evidence.' },
      { label: 'Rollback policy', path: entityTabPath('releases', 'rollback-policy'), description: 'Whether a missing plan or stale rehearsal warns or blocks.' },
      { label: 'Event types', path: entityTabPath('releases', 'event-types'), description: 'Release calendar event types.' },
      { label: 'Lifecycle', path: entityTabPath('releases', 'lifecycle'), description: 'States and transitions for releases.' },
      { label: 'Scope-change rules', path: '/admin/releases/scope-change-rules', description: 'Change kinds and what counts as scope creep.' },
      { label: 'RAID settings', path: '/admin/releases/raid', description: 'RAID categories, RAG thresholds and defaults.' },
      { label: 'Custom fields', path: entityTabPath('releases', 'fields'), description: 'Tenant-defined fields on every release.' },
      { label: 'Scope item fields', path: entityTabPath('release-changes', 'fields'), description: 'Tenant-defined fields on release scope items.' },
    ],
  },
  {
    label: 'Delivery',
    icon: <LocalShippingIcon />,
    requires: 'admin',
    children: [
      { label: 'Change requests', path: entityTabPath('change-requests', 'fields'), description: 'Custom fields and lifecycle for change requests.' },
      { label: 'Builds', path: entityTabPath('builds', 'fields'), description: 'Custom fields on builds.' },
      { label: 'Deployments', path: entityTabPath('deployments', 'fields'), description: 'Custom fields on deployments.' },
      { label: 'Incidents', path: entityTabPath('incidents', 'fields'), description: 'Custom fields and lifecycle for incidents.' },
      { label: 'Systems', path: entityTabPath('systems', 'fields'), description: 'Custom fields on systems.' },
      { label: 'Subsystems', path: entityTabPath('subsystems', 'fields'), description: 'Custom fields on subsystems.' },
      { label: 'Component types', path: '/admin/component-types', description: 'Infrastructure component types and their field schemas.' },
      { label: 'Environment request fields', path: entityTabPath('environment-requests', 'fields'), description: 'Custom fields on environment requests.' },
    ],
  },
  {
    label: 'Integrations',
    icon: <ExtensionIcon />,
    requires: 'admin',
    children: [
      { label: 'API keys', path: '/admin/api-keys', description: 'Keys and scopes for pipelines and webhooks.' },
      { label: 'GitHub', path: '/admin/github', description: 'Connect GitHub for repository scanning and drift checks.' },
    ],
  },
  {
    label: 'Platform',
    icon: <AdminPanelSettingsIcon />,
    requires: 'masterAdmin',
    children: [
      { label: 'Tenants', path: '/admin/tenants', description: 'Provision tenants, their first Admin, and sign in as one.' },
    ],
  },
];

/**
 * A master admin who is not an Admin of the active tenant administers the
 * PLATFORM, not this tenant, so their admin menu is the Platform section
 * alone (design spec §4.5). For everyone else a child inherits its
 * section's `requires` unless it sets its own — which is what keeps
 * *User groups* readable by any tenant member (B3a's read/write split).
 */
export function visibleAdminNav(user: NavUser | null): NavGroup[] {
  const platformOnly = user?.is_master_admin === true && user?.role !== 'Admin';
  return adminNav
    .filter((section) => !platformOnly || section.label === 'Platform')
    .map((section) => ({
      ...section,
      children: section.children.filter((c) =>
        userSatisfies(user, c.requires ?? section.requires)
      ),
    }))
    .filter((section) => section.children.length > 0);
}
