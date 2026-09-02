import type { EntityType } from '../../types/customField';

/** URL segment for an admin entity page: `/admin/<entity>/<tab>`. */
export type AdminEntity =
  | 'environments'
  | 'environment-requests'
  | 'bookings'
  | 'releases'
  | 'release-changes'
  | 'change-requests'
  | 'builds'
  | 'deployments'
  | 'incidents'
  | 'systems'
  | 'subsystems';

export type EntityPanel =
  | 'fields'
  | 'lifecycle'
  | 'booking-types'
  | 'event-types'
  | 'gate-types'
  | 'rollback-policy'
  | 'tiers'
  | 'naming-policy'
  | 'lifecycle-policy';

export interface EntityConfigTab {
  key: string;
  label: string;
  panel: EntityPanel;
}

export interface EntityConfigPage {
  entity: AdminEntity;
  label: string;
  entityType: EntityType;
  tabs: EntityConfigTab[];
}

const FIELDS: EntityConfigTab = { key: 'fields', label: 'Custom fields', panel: 'fields' };
const LIFECYCLE: EntityConfigTab = { key: 'lifecycle', label: 'Lifecycle', panel: 'lifecycle' };

/**
 * The one table that says which entity has which configuration tab. The
 * admin drawer's items, the /admin hub and the EntityConfig page all derive
 * from it — replacing the seven `*_SUPPORTED` lists and the arithmetic tab
 * indices EntityConfig used to compute from them.
 */
export const ENTITY_CONFIG_PAGES: EntityConfigPage[] = [
  {
    entity: 'environments',
    label: 'Environments',
    entityType: 'environment',
    tabs: [
      FIELDS,
      { key: 'tiers', label: 'Tiers', panel: 'tiers' },
      { key: 'naming-policy', label: 'Naming policy', panel: 'naming-policy' },
      { key: 'lifecycle-policy', label: 'Lifecycle & decommissioning', panel: 'lifecycle-policy' },
    ],
  },
  {
    entity: 'environment-requests',
    label: 'Environment requests',
    entityType: 'environment_request',
    tabs: [FIELDS, LIFECYCLE],
  },
  {
    entity: 'bookings',
    label: 'Bookings',
    entityType: 'booking',
    tabs: [FIELDS, { key: 'types', label: 'Booking types', panel: 'booking-types' }, LIFECYCLE],
  },
  {
    entity: 'releases',
    label: 'Releases',
    entityType: 'release',
    tabs: [
      FIELDS,
      LIFECYCLE,
      { key: 'event-types', label: 'Event types', panel: 'event-types' },
      { key: 'gate-types', label: 'Gate types', panel: 'gate-types' },
      { key: 'rollback-policy', label: 'Rollback policy', panel: 'rollback-policy' },
    ],
  },
  { entity: 'release-changes', label: 'Release scope items', entityType: 'release_change', tabs: [FIELDS] },
  { entity: 'change-requests', label: 'Change requests', entityType: 'change_request', tabs: [FIELDS, LIFECYCLE] },
  { entity: 'builds', label: 'Builds', entityType: 'build', tabs: [FIELDS] },
  { entity: 'deployments', label: 'Deployments', entityType: 'deployment', tabs: [FIELDS] },
  { entity: 'incidents', label: 'Incidents', entityType: 'incident', tabs: [FIELDS, LIFECYCLE] },
  { entity: 'systems', label: 'Systems', entityType: 'system', tabs: [FIELDS] },
  { entity: 'subsystems', label: 'Subsystems', entityType: 'subsystem', tabs: [FIELDS] },
];

export function entityConfigPage(entity: string | undefined): EntityConfigPage | undefined {
  return ENTITY_CONFIG_PAGES.find((p) => p.entity === entity);
}

export function entityTabPath(entity: AdminEntity, tab: string): string {
  return `/admin/${entity}/${tab}`;
}
