import BusinessIcon from '@mui/icons-material/Business';
import ComputerIcon from '@mui/icons-material/Computer';
import EventAvailableIcon from '@mui/icons-material/EventAvailable';
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch';
import LocalShippingIcon from '@mui/icons-material/LocalShipping';
import ExtensionIcon from '@mui/icons-material/Extension';
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings';
import { entityConfigPage, entityTabPath, type AdminEntity } from '../pages/admin/entityConfigTabs';
import { userSatisfies, type NavGroup, type NavItem, type NavUser } from './navConfig';

/**
 * Expand an entity into one drawer item per its configuration tab, in the
 * order `ENTITY_CONFIG_PAGES` declares — that table is the single source of
 * truth for a tab's label, order and description, so a section built this
 * way can never disagree with the tab strip `EntityConfig` renders for it.
 */
function entityTabItems(entity: AdminEntity): NavItem[] {
  const page = entityConfigPage(entity);
  if (!page) throw new Error(`Unknown admin entity: ${entity}`);
  return page.tabs.map((tab) => ({
    label: tab.label,
    path: entityTabPath(entity, tab.key),
    description: tab.description,
  }));
}

/**
 * A single drawer item for an entity that isn't this section's own — it
 * navigates to the entity's page (landing on its first tab), labelled with
 * that entity's own name rather than one of its tab names.
 */
function entityPageItem(entity: AdminEntity, description: string): NavItem {
  const page = entityConfigPage(entity);
  if (!page) throw new Error(`Unknown admin entity: ${entity}`);
  return {
    label: page.label,
    path: entityTabPath(entity, page.tabs[0].key),
    description,
  };
}

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
      ...entityTabItems('environments'),
      entityPageItem('environment-requests', 'Custom fields and lifecycle for environment requests.'),
    ],
  },
  {
    label: 'Bookings',
    icon: <EventAvailableIcon />,
    requires: 'admin',
    children: entityTabItems('bookings'),
  },
  {
    label: 'Releases',
    icon: <RocketLaunchIcon />,
    requires: 'admin',
    children: [
      { label: 'Templates', path: '/admin/releases/templates', description: 'Reusable release blueprints: phases, gates and events.' },
      ...entityTabItems('releases'),
      { label: 'Scope-change rules', path: '/admin/releases/scope-change-rules', description: 'Change kinds and what counts as scope creep.' },
      { label: 'RAID settings', path: '/admin/releases/raid', description: 'RAID categories, RAG thresholds and defaults.' },
      entityPageItem('release-changes', 'Tenant-defined fields on release scope items.'),
    ],
  },
  {
    label: 'Delivery',
    icon: <LocalShippingIcon />,
    requires: 'admin',
    children: [
      entityPageItem('change-requests', 'Custom fields and lifecycle for change requests.'),
      entityPageItem('builds', 'Custom fields on builds.'),
      entityPageItem('deployments', 'Custom fields on deployments.'),
      entityPageItem('incidents', 'Custom fields and lifecycle for incidents.'),
      entityPageItem('systems', 'Custom fields on systems.'),
      entityPageItem('subsystems', 'Custom fields on subsystems.'),
      { label: 'Component types', path: '/admin/component-types', description: 'Infrastructure component types and their field schemas.' },
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
