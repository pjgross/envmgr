import { Navigate, generatePath, useParams } from 'react-router-dom';
import { entityTabPath, type AdminEntity } from '../pages/admin/entityConfigTabs';

export interface LegacyRedirect {
  from: string;
  to: string;
}

const LEGACY_CONFIG_SLUGS: Record<string, string> = {
  system: 'systems',
  subsystem: 'subsystems',
  environment: 'environments',
  booking: 'bookings',
  'change-request': 'change-requests',
  release: 'releases',
  'release-change': 'release-changes',
  build: 'builds',
  deployment: 'deployments',
  incident: 'incidents',
  'environment-request': 'environment-requests',
};

/**
 * Old path → new path, kept for ONE release so testers' bookmarks don't 404.
 * In-app links were rewritten; nothing in src/ should navigate to a `from`.
 * Remove this file, its routes and its test together.
 */
// eslint-disable-next-line react-refresh/only-export-components
export const LEGACY_REDIRECTS: LegacyRedirect[] = [
  { from: '/tenant/users', to: '/admin/users' },
  { from: '/tenant/settings', to: '/admin/settings' },
  { from: '/tenant/groups', to: '/admin/user-groups' },
  { from: '/tenant/groups/:id', to: '/admin/user-groups/:id' },
  { from: '/tenant/projects', to: '/projects' },
  { from: '/tenant/projects/:id', to: '/projects/:id' },
  { from: '/tenant/environment-groups', to: '/environment-groups' },
  { from: '/tenant/environment-groups/:id', to: '/environment-groups/:id' },
  { from: '/tenant/api-keys', to: '/admin/api-keys' },
  { from: '/tenant/raid-settings', to: '/admin/releases/raid' },
  { from: '/admin/config/component-types', to: '/admin/component-types' },
  // The `to` here MUST be the query form, not `/admin/${entity}/fields`: that
  // segment form still resolves (as a redirect registered in App.tsx), but
  // landing on it would mean this table's own redirect immediately triggers
  // a second one — exactly the "never emit a URL that immediately redirects"
  // rule the drawer follows, extended to this table's targets too.
  ...Object.entries(LEGACY_CONFIG_SLUGS).map(([slug, entity]) => ({
    from: `/admin/config/${slug}`,
    to: entityTabPath(entity as AdminEntity, 'fields'),
  })),
  { from: '/admin/scope-change-rules', to: '/admin/releases/scope-change-rules' },
  { from: '/admin/release-templates', to: '/admin/releases/templates' },
  { from: '/admin/release-templates/:id', to: '/admin/releases/templates/:id' },
];

export function LegacyRedirectRoute({ to }: { to: string }) {
  const params = useParams();
  return <Navigate replace to={generatePath(to, params)} />;
}
