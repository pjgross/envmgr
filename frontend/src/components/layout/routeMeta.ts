import { generatePath, matchPath } from 'react-router-dom';
import { ENTITY_CONFIG_PAGES } from '../../pages/admin/entityConfigTabs';

export type RouteMeta = { label: string; parent?: string };

/**
 * Path pattern → where it sits. STATIC by design (spec §6): a page's entity
 * name reaches document.title through usePageTitle(name), never through here.
 * A table that depended on fetched state would have two sources of truth and
 * could not be unit-tested (see ROUTE_META's "holds no dynamic data" test).
 *
 * Keys are route PATTERNS (`/environments/:id`), matched against a concrete
 * pathname with `matchPath`. Labels are copied verbatim from navConfig.tsx /
 * adminNavConfig.tsx — two names for one page is the drift this whole
 * programme exists to remove.
 *
 * Nav *groups* (Catalogue, Bookings, Releases, Insights, and every
 * adminNavConfig section) have no route of their own, so they contribute no
 * entry and no parent here — a page nested only under a group sits at the
 * root of its own breadcrumb trail, exactly like `/environments` in the
 * tests below.
 *
 * Labels are copied from the nav verbatim, except where a drawer label is
 * only meaningful under its group header — the drawer item is plain "List"
 * under both the Releases and the Bookings group, which reads fine there but
 * would be a naked "List" in a browser tab or a breadcrumb with no group
 * header beside it. `/releases` and `/bookings/list` hold the page's own
 * name ("Releases", "Bookings") instead for exactly that reason.
 */
const adminEntityRoutes: Record<string, RouteMeta> = Object.fromEntries(
  ENTITY_CONFIG_PAGES.map((page) => [`/admin/${page.entity}`, { label: page.label, parent: '/admin' }])
);

export const ROUTE_META: Record<string, RouteMeta> = {
  '/dashboard': { label: 'Dashboard' },
  '/my-work': { label: 'My work' },

  // Catalogue
  '/systems': { label: 'Systems' },
  '/systems/:id': { label: 'System', parent: '/systems' },
  '/environments': { label: 'Environments' },
  // Declared before its literal sibling on purpose: the dynamic pattern
  // matches "compare" as `id` too, so this ordering is a live check that the
  // specificity scorer below — not insertion order — is what makes the
  // literal win (see routeMeta.test.ts's specificity-scorer test).
  '/environments/:id': { label: 'Environment', parent: '/environments' },
  '/environments/compare': { label: 'Compare environments' },
  '/infrastructure/hosts': { label: 'Hosts' },
  '/import': { label: 'Import' },

  // Bookings
  '/bookings/calendar': { label: 'Calendar' },
  '/bookings/list': { label: 'Bookings' }, // drawer says "List" — see the note above
  // Parented to the list, not the calendar: BookingDetail's own "Back to"
  // link and the calendar are two different ways in, and the list is the
  // one that still makes sense to land back on regardless of which way a
  // visitor arrived — the calendar is a view over a date range a booking
  // may not even fall inside.
  '/bookings/:id': { label: 'Booking', parent: '/bookings/list' },
  '/environment-requests': { label: 'Environment requests' },
  '/environment-requests/new': { label: 'New environment request', parent: '/environment-requests' },
  '/environment-requests/:id': { label: 'Environment request', parent: '/environment-requests' },
  '/change-requests': { label: 'Change requests' },
  '/change-requests/:id': { label: 'Change request', parent: '/change-requests' },
  '/projects': { label: 'Projects' },
  '/projects/:id': { label: 'Project', parent: '/projects' },
  '/environment-groups': { label: 'Environment groups' },
  '/environment-groups/:id': { label: 'Environment group', parent: '/environment-groups' },
  '/contentions': { label: 'Contentions' },
  '/decommissions': { label: 'Decommissions' },

  // Releases
  '/releases': { label: 'Releases' }, // drawer says "List" — see the note above
  '/releases/calendar': { label: 'Calendar' },
  '/releases/timeline': { label: 'Timeline' },
  '/releases/scope-windows': { label: 'Scope windows' },
  '/releases/analytics': { label: 'Analytics' },
  // Same deliberate ordering as /environments above: /releases/:id is
  // declared before /releases/new, which it would otherwise swallow as
  // `id: "new"` were the scorer not doing the picking.
  '/releases/:id': { label: 'Release', parent: '/releases' },
  // App.tsx routes `/releases/new` to <ReleaseList />, which ignores the
  // pathname — a visitor here sees the list, not a page named "New release".
  // This entry exists only so a stale bookmark from before that page was
  // removed doesn't instead fall through to `/releases/:id` and fetch
  // `id: "new"`.
  '/releases/new': { label: 'New release', parent: '/releases' },
  '/builds': { label: 'Builds' },
  '/builds/:id': { label: 'Build', parent: '/builds' },
  '/deployments': { label: 'Deployments' },
  '/deployments/:id': { label: 'Deployment', parent: '/deployments' },
  '/incidents': { label: 'Incidents' },
  // /incidents/new and /incidents/:id/edit both render the same <IncidentForm>
  // component, but they are different navigation contexts and get different
  // parents: creating one is reached from the list, editing one is reached
  // from that incident's own page, so their breadcrumb trails should — and
  // do — differ in depth even though the page underneath is identical.
  '/incidents/new': { label: 'New incident', parent: '/incidents' },
  '/incidents/:id': { label: 'Incident', parent: '/incidents' },
  '/incidents/:id/edit': { label: 'Edit incident', parent: '/incidents/:id' },
  '/pir-actions': { label: 'PIR actions' },

  // Insights
  '/insights/dora': { label: 'DORA metrics' },
  '/insights/health': { label: 'Environment health' },

  // Administration — literal admin-only routes. The per-entity config pages
  // (`/admin/environments`, `/admin/bookings`, …) are generated below from
  // ENTITY_CONFIG_PAGES, the single source of truth entityConfigTabs.ts
  // already establishes for those labels — inventing a parallel slug list
  // here is exactly what the task brief warns against.
  '/admin': { label: 'Administration' },
  '/admin/users': { label: 'Users', parent: '/admin' },
  '/admin/user-groups': { label: 'User groups', parent: '/admin' },
  '/admin/user-groups/:id': { label: 'User group', parent: '/admin/user-groups' },
  '/admin/settings': { label: 'Tenant settings', parent: '/admin' },
  '/admin/api-keys': { label: 'API keys', parent: '/admin' },
  '/admin/github': { label: 'GitHub', parent: '/admin' },
  '/admin/component-types': { label: 'Component types', parent: '/admin' },
  '/admin/releases/templates': { label: 'Templates', parent: '/admin' },
  '/admin/releases/templates/:id': { label: 'Template', parent: '/admin/releases/templates' },
  '/admin/releases/scope-change-rules': { label: 'Scope-change rules', parent: '/admin' },
  '/admin/releases/raid': { label: 'RAID settings', parent: '/admin' },
  '/admin/tenants': { label: 'Tenants', parent: '/admin' },
  '/admin/tenants/:tenantId': { label: 'Tenant', parent: '/admin/tenants' },

  ...adminEntityRoutes,
};

/**
 * Specificity score for a route pattern, used to pick a winner when more than
 * one pattern matches a pathname (e.g. `/environments/compare` also satisfies
 * `/environments/:id` with `id: "compare"`). A literal segment scores far
 * higher than a dynamic (`:x`) or splat (`*`) segment at the same depth, so
 * the most specific — and, for a human, most obviously correct — pattern
 * always wins regardless of where either entry sits in ROUTE_META. Ties
 * (which nothing in this table currently produces) fall back to declaration
 * order, since Object.keys iterates string keys in insertion order — a
 * documented, deterministic fallback rather than an accidental one.
 */
function specificity(pattern: string): number {
  return pattern
    .split('/')
    .filter(Boolean)
    .reduce((score, segment) => score + (segment.startsWith(':') || segment === '*' ? 1 : 100), 0);
}

function matchRoutePattern(pathname: string): string | undefined {
  let best: string | undefined;
  let bestScore = -1;
  for (const pattern of Object.keys(ROUTE_META)) {
    if (!matchPath(pattern, pathname)) continue;
    const score = specificity(pattern);
    if (score > bestScore) {
      best = pattern;
      bestScore = score;
    }
  }
  return best;
}

export function breadcrumbsFor(pathname: string): Array<{ label: string; to?: string }> {
  const pattern = matchRoutePattern(pathname);
  if (!pattern) return [];
  // A DYNAMIC parent (only `/incidents/:id`, today) must be resolved against
  // the concrete pathname, not linked as the literal pattern string — a crumb
  // whose href is `/incidents/:id` matches that route with `id === ':id'` and
  // the detail page fetches NaN. The child's params are a superset of every
  // ancestor's (an ancestor pattern is always a prefix of the child's), so
  // one match against the leaf pattern is enough to resolve every ancestor.
  const params = matchPath(pattern, pathname)?.params ?? {};
  const trail: Array<{ label: string; to?: string }> = [];
  for (let p: string | undefined = pattern; p; p = ROUTE_META[p]?.parent) {
    const to = p.includes(':') ? generatePath(p, params) : p;
    trail.unshift({ label: ROUTE_META[p].label, to });
  }
  delete trail[trail.length - 1].to;
  return trail;
}
